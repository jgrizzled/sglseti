from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest
from astropy.time import Time, TimeDelta
from support import AU_PER_PC, FakeEphemeris

from sglseti.ephemeris import AstropyEphemeris
from sglseti.errors import GenerationError
from sglseti.generate import generate_loci, materialize_epochs
from sglseti.models import (
    AstrometricState,
    CoordinateProduct,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    Epoch,
    GeometryRequest,
    Observer,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    Target,
    TimeGrid,
    TimeList,
    TimeSingle,
    UncertaintyMethod,
    Validity,
)
from sglseti.targets import TargetRegistry

KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / (
    "de440s_excerpt_2010-2035.bsp"
)

EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))

T1 = Time("2021-11-06T00:00:00", scale="utc")
T2 = Time("2022-03-01T12:00:00", scale="utc")


def make_target(target_id: str = "synth") -> Target:
    return Target(
        target_id=target_id,
        display_name="Synthetic",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=100.0,
            pm_dec_mas_per_yr=-50.0,
            reference_epoch_jyear=2016.0,
            reference_epoch_scale="tdb",
            source="unit test values",
            distance_pc=200_000.0 / AU_PER_PC,
            radial_velocity_km_s=0.0,
        ),
    )


def make_registry(*targets: Target) -> TargetRegistry:
    return TargetRegistry.from_targets(targets or (make_target(),))


def make_request(**overrides: object) -> GeometryRequest:
    values: dict = dict(
        target_ids=("synth",),
        roles=(Role.RX, Role.TX),
        time=TimeList(
            epochs=(
                Epoch(epoch_id="e1", time=T1, metadata={"dataset_id": "D1"}),
                Epoch(epoch_id="e2", time=T2),
            )
        ),
        observer=Observer.earth_center(),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=3),
        model_id="tusay2022_eq5_7_v1",
    )
    values.update(overrides)
    return GeometryRequest(**values)


def test_product_shape_and_documented_order() -> None:
    result = generate_loci(make_request(), make_registry(), ephemeris=EPHEMERIS)
    # 1 target x 2 roles x 2 epochs x 3 segments.
    assert len(result.samples) == 12
    assert len(result.corridors) == 4
    keys = [(s.target_id, s.role, s.epoch_id) for s in result.samples]
    assert keys == (
        [("synth", Role.RX, "e1")] * 3
        + [("synth", Role.RX, "e2")] * 3
        + [("synth", Role.TX, "e1")] * 3
        + [("synth", Role.TX, "e2")] * 3
    )
    for corridor in result.corridors:
        z_values = [sample.z_au for sample in corridor.samples]
        assert z_values == sorted(z_values)
        assert corridor.z_min_au == 550.0 and corridor.z_max_au == 2500.0
        assert len(corridor.samples) == 3


def test_epoch_ids_and_metadata_join_back() -> None:
    request = make_request()
    result = generate_loci(request, make_registry(), ephemeris=EPHEMERIS)
    assert {sample.epoch_id for sample in result.samples} == {"e1", "e2"}
    # Pass-through metadata is joinable from the request via epoch_id.
    assert isinstance(request.time, TimeList)
    metadata = {epoch.epoch_id: epoch.metadata for epoch in request.time.epochs}
    for sample in result.samples:
        assert sample.epoch_id in metadata
    assert metadata["e1"] == {"dataset_id": "D1"}


def test_deterministic_across_runs_and_registry_order() -> None:
    request = make_request()
    first = generate_loci(request, make_registry(), ephemeris=EPHEMERIS)
    second = generate_loci(request, make_registry(), ephemeris=EPHEMERIS)
    assert first.calculation_id == second.calculation_id
    assert first.samples == second.samples
    assert first.corridors == second.corridors
    # Extra unrelated targets in the registry change nothing.
    extended = make_registry(make_target(), make_target("other"))
    third = generate_loci(request, extended, ephemeris=EPHEMERIS)
    assert third.calculation_id == first.calculation_id
    assert third.samples == first.samples


def test_single_vs_batch_numerical_equivalence() -> None:
    batch = generate_loci(make_request(), make_registry(), ephemeris=EPHEMERIS)
    single = generate_loci(
        make_request(time=TimeSingle(epoch=Epoch(epoch_id="e1", time=T1))),
        make_registry(),
        ephemeris=EPHEMERIS,
    )
    batch_e1 = [s for s in batch.samples if s.epoch_id == "e1"]
    assert len(batch_e1) == len(single.samples)
    for from_batch, from_single in zip(batch_e1, single.samples, strict=True):
        assert from_batch.icrs_ra_deg == from_single.icrs_ra_deg
        assert from_batch.icrs_dec_deg == from_single.icrs_dec_deg
        assert (
            from_batch.catalog_direction_epoch_tdb_jd
            == from_single.catalog_direction_epoch_tdb_jd
        )
        assert from_batch.sample_id == from_single.sample_id
        # calculation_id legitimately differs (different request).
        assert from_batch.calculation_id != from_single.calculation_id


def test_unknown_target_fails_clearly() -> None:
    with pytest.raises(GenerationError, match=r"unknown target ID\(s\) \['nope'\]"):
        generate_loci(
            make_request(target_ids=("nope",)), make_registry(), ephemeris=EPHEMERIS
        )


def test_grid_materialization() -> None:
    grid = TimeGrid(start=T1, stop=T1 + TimeDelta(1800, format="sec"), cadence_s=600.0)
    epochs = materialize_epochs(grid)
    assert [e.epoch_id for e in epochs] == [
        "grid-000000",
        "grid-000001",
        "grid-000002",
        "grid-000003",
    ]
    seconds = [float((e.time - T1).sec) for e in epochs]
    assert seconds == pytest.approx([0.0, 600.0, 1200.0, 1800.0], abs=1e-6)

    result = generate_loci(
        make_request(time=grid), make_registry(), ephemeris=EPHEMERIS
    )
    assert len(result.samples) == 2 * 4 * 3


def test_grid_materialization_limit() -> None:
    grid = TimeGrid(start=T1, stop=T1 + TimeDelta(365, format="jd"), cadence_s=0.01)
    with pytest.raises(GenerationError, match="limit is"):
        materialize_epochs(grid)


def test_coverage_failure_isolated_to_its_combination() -> None:
    # Coverage includes T1 but not T2.
    limited = FakeEphemeris(
        (0.004, -0.002, 0.001),
        (0.558, -0.744, -0.323),
        coverage_jd=(2459000.0, 2459600.0),
    )
    result = generate_loci(make_request(), make_registry(), ephemeris=limited)
    by_epoch = {"e1": [], "e2": []}
    for sample in result.samples:
        by_epoch[sample.epoch_id].append(sample)
    assert all(s.validity is Validity.VALID for s in by_epoch["e1"])
    assert all(s.validity is Validity.INVALID for s in by_epoch["e2"])
    for sample in by_epoch["e2"]:
        assert math.isnan(sample.icrs_ra_deg)
        assert any(w.startswith("ephemeris_out_of_coverage") for w in sample.warnings)
    assert "invalid_sample_count:6" in result.warnings


def test_strict_mode_fails_on_invalid() -> None:
    limited = FakeEphemeris(
        (0.004, -0.002, 0.001),
        (0.558, -0.744, -0.323),
        coverage_jd=(2459000.0, 2459600.0),
    )
    with pytest.raises(GenerationError, match="strict mode: invalid sample.*e2"):
        generate_loci(make_request(), make_registry(), ephemeris=limited, strict=True)


def test_uncertainty_labeling() -> None:
    unpadded = generate_loci(make_request(), make_registry(), ephemeris=EPHEMERIS)
    assert "uncertainty_not_propagated" in unpadded.warnings
    assert all(
        s.uncertainty_method is UncertaintyMethod.NOT_PROPAGATED
        for s in unpadded.samples
    )
    padded = generate_loci(
        make_request(assumed_half_width_arcsec=30.0),
        make_registry(),
        ephemeris=EPHEMERIS,
    )
    assert "uncertainty_not_propagated" not in padded.warnings
    assert all(
        s.uncertainty_method is UncertaintyMethod.ASSUMED for s in padded.samples
    )
    for corridor in padded.corridors:
        assert corridor.assumed_half_width_arcsec == 30.0
        assert corridor.uncertainty_method is UncertaintyMethod.ASSUMED


def test_optional_products_default_to_none() -> None:
    result = generate_loci(make_request(), make_registry(), ephemeris=EPHEMERIS)
    for sample in result.samples:
        assert sample.cirs_ra_deg is None
        assert sample.altaz_alt_deg is None
        assert sample.rate_ra_cosdec_arcsec_per_hr is None


def test_rates_and_apparent_products_populated() -> None:
    site = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)
    request = make_request(
        observer=site,
        coordinate_products=(
            CoordinateProduct.ICRS,
            CoordinateProduct.CIRS,
            CoordinateProduct.ALTAZ,
        ),
        include_rates=True,
        time=TimeSingle(epoch=Epoch(epoch_id="e1", time=T1)),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=2),
    )
    result = generate_loci(request, make_registry(), ephemeris=EPHEMERIS)
    assert len(result.samples) == 4
    for sample in result.samples:
        assert sample.cirs_ra_deg is not None
        assert sample.cirs_dec_deg is not None
        assert sample.altaz_alt_deg is not None and -90 <= sample.altaz_alt_deg <= 90
        assert sample.altaz_az_deg is not None and 0 <= sample.altaz_az_deg < 360
        assert sample.rate_ra_cosdec_arcsec_per_hr is not None
        assert sample.rate_dec_arcsec_per_hr is not None


def test_calculation_id_is_path_independent(tmp_path: Path) -> None:
    moved = tmp_path / "renamed-kernel.bsp"
    shutil.copy(KERNEL, moved)
    request_original = make_request(
        ephemeris=EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL))
    )
    request_moved = make_request(
        ephemeris=EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(moved))
    )
    registry = make_registry()
    original = generate_loci(
        request_original, registry, ephemeris=AstropyEphemeris(request_original.ephemeris)
    )
    relocated = generate_loci(
        request_moved, registry, ephemeris=AstropyEphemeris(request_moved.ephemeris)
    )
    assert original.calculation_id == relocated.calculation_id
    # And a genuinely different ephemeris changes the identity.
    with_fake = generate_loci(request_original, registry, ephemeris=EPHEMERIS)
    assert with_fake.calculation_id != original.calculation_id


def test_request_id_is_path_independent() -> None:
    from sglseti.provenance import request_id

    a = make_request(
        ephemeris=EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path="/a/kernel.bsp")
    )
    b = make_request(
        ephemeris=EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path="/b/kernel.bsp")
    )
    assert request_id(a) == request_id(b)
    assert request_id(a) != request_id(make_request())
