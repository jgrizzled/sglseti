"""Archive-scale execution (§3.4): caching, chunking, vectorization, streaming.

Every feature here is a pure execution optimization: results must be
IDENTICAL to the unoptimized paths, which is what these tests pin down.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris

from sglseti.errors import GenerationError
from sglseti.export import write_products, write_samples_stream
from sglseti.generate import (
    generate_loci,
    iter_locus_chunks,
    plan_calculation,
)
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    Epoch,
    GeometryRequest,
    Observer,
    OrbitComponent,
    OutputFormat,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    Target,
    TimeList,
)
from sglseti.providers import (
    EarthCenterObserverV1,
    TerrestrialSiteObserverV1,
    clear_provider_cache,
    provider_cache_stats,
    resolve_target_state_provider,
)
from sglseti.targets import TargetRegistry

EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
T1 = Time("2021-11-06T00:00:00", scale="utc")
T2 = Time("2022-03-01T12:00:00", scale="utc")
EPOCHS_VECTOR = Time(np.linspace(2015.0, 2030.0, 25), format="jyear", scale="tdb")


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


def make_request(**overrides: object) -> GeometryRequest:
    values: dict = dict(
        target_ids=("synth",),
        roles=(Role.RX, Role.TX),
        time=TimeList(
            epochs=(
                Epoch(epoch_id="e1", time=T1),
                Epoch(epoch_id="e2", time=T2),
            )
        ),
        observer=Observer.earth_center(),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=5),
        model_id="tusay2022_eq5_7_v1",
        output_formats=(OutputFormat.ECSV, OutputFormat.CSV),
    )
    values.update(overrides)
    return GeometryRequest(**values)


REGISTRY = TargetRegistry.from_targets((make_target(),))


# ---------------------------------------------------------------------------
# Identity-keyed caching
# ---------------------------------------------------------------------------


def test_provider_resolution_is_memoized_by_content() -> None:
    clear_provider_cache()
    first = resolve_target_state_provider(make_target())
    second = resolve_target_state_provider(make_target())
    assert first is second  # equal content, one provider
    stats = provider_cache_stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    # Different scientific content resolves to a different provider.
    other = resolve_target_state_provider(make_target("other"))
    assert other is not first


def test_state_memo_is_bit_identical_and_scale_aware() -> None:
    clear_provider_cache()
    provider = resolve_target_state_provider(make_target())
    fresh = provider.state_at(T1)
    cached = provider.state_at(T1.tdb)  # same instant, different scale
    assert cached.ra_deg == fresh.ra_deg
    assert cached.dec_deg == fresh.dec_deg
    assert cached.distance_au == fresh.distance_au
    assert cached.epoch is not fresh.epoch  # the caller's epoch is kept
    clear_provider_cache()
    recomputed = resolve_target_state_provider(make_target()).state_at(T1)
    assert recomputed.ra_deg == fresh.ra_deg
    assert recomputed.dec_deg == fresh.dec_deg


def test_generate_results_identical_with_cold_and_warm_cache() -> None:
    request = make_request()
    clear_provider_cache()
    cold = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    warm = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    assert cold.samples == warm.samples
    assert cold.calculation_id == warm.calculation_id
    assert provider_cache_stats()["hits"] > 0


# ---------------------------------------------------------------------------
# Vectorized evaluation
# ---------------------------------------------------------------------------


def _orbit_target() -> Target:
    from sglseti.models import OrbitSolution

    base = make_target("binary-a")
    return Target(
        target_id="binary-a",
        display_name="Binary A",
        endpoint_kind=EndpointKind.COMPONENT,
        astrometry=base.astrometry,
        provider_id="two_body_orbit_v1",
        orbit=OrbitSolution(
            period_yr=79.91,
            periastron_epoch_jyear=1955.66,
            eccentricity=0.524,
            semimajor_axis_arcsec=17.66,
            inclination_deg=79.32,
            ascending_node_deg=204.85,
            arg_periastron_deg=232.3,
            mass_fraction_secondary=0.4617,
            component=OrbitComponent.PRIMARY,
            source="unit test values",
        ),
    )


def _accel_target() -> Target:
    from sglseti.models import AccelerationTerms

    base = make_target("accel")
    return Target(
        target_id="accel",
        display_name="Accelerating",
        endpoint_kind=EndpointKind.STAR,
        astrometry=base.astrometry,
        provider_id="acceleration_astrometry_v1",
        acceleration=AccelerationTerms(0.9, -0.4, "unit test values"),
    )


@pytest.mark.parametrize(
    "target_factory", [make_target, _accel_target, _orbit_target]
)
def test_vectorized_states_match_scalar(target_factory) -> None:
    clear_provider_cache()
    provider = resolve_target_state_provider(target_factory())
    vector_states = provider.states_at(EPOCHS_VECTOR)
    assert len(vector_states) == len(EPOCHS_VECTOR)
    for index, state in enumerate(vector_states):
        scalar = provider._compute_state(EPOCHS_VECTOR[index])
        assert state.ra_deg == scalar.ra_deg
        assert state.dec_deg == scalar.dec_deg
        assert state.distance_au == scalar.distance_au


def test_vectorized_observer_positions_match_scalar() -> None:
    times = Time(np.linspace(2020.0, 2021.0, 7), format="jyear", scale="tdb")
    earth = EarthCenterObserverV1(Observer.earth_center(), EPHEMERIS)
    positions = earth.positions_au(times)
    assert positions.shape == (7, 3)
    for index in range(7):
        assert tuple(positions[index]) == earth.state_at(times[index]).position_au

    from sglseti.ephemeris import AstropyEphemeris

    site = TerrestrialSiteObserverV1(
        Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43),
        AstropyEphemeris(),
    )
    site_positions = site.positions_au(times)
    assert site_positions.shape == (7, 3)
    for index in range(7):
        expected = np.asarray(site.state_at(times[index]).position_au)
        assert np.allclose(site_positions[index], expected, rtol=0, atol=1e-15)


# ---------------------------------------------------------------------------
# Deterministic chunked execution
# ---------------------------------------------------------------------------


def test_chunks_reassemble_the_batch_result_exactly() -> None:
    request = make_request()
    batch = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    chunks = list(iter_locus_chunks(request, REGISTRY, ephemeris=EPHEMERIS))
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.chunk_count == len(chunks) for chunk in chunks)
    assert tuple(chunk.corridor for chunk in chunks) == batch.corridors
    reassembled = tuple(
        sample for chunk in chunks for sample in chunk.corridor.samples
    )
    assert reassembled == batch.samples
    assert chunks[0].corridor.calculation_id == batch.calculation_id


def test_chunk_ranges_are_independently_reproducible() -> None:
    request = make_request()
    full = list(iter_locus_chunks(request, REGISTRY, ephemeris=EPHEMERIS))
    partial = list(
        iter_locus_chunks(request, REGISTRY, ephemeris=EPHEMERIS, start=1, stop=3)
    )
    assert [chunk.chunk_index for chunk in partial] == [1, 2]
    assert [chunk.corridor for chunk in partial] == [
        chunk.corridor for chunk in full[1:3]
    ]


def test_plan_reuse_and_validation() -> None:
    request = make_request()
    plan = plan_calculation(request, REGISTRY, ephemeris=EPHEMERIS)
    assert plan.chunk_count == 1 * 2 * 2  # targets x roles x epochs
    chunks = list(
        iter_locus_chunks(request, REGISTRY, plan=plan, ephemeris=EPHEMERIS)
    )
    assert len(chunks) == plan.chunk_count
    other_request = make_request(roles=(Role.RX,))
    with pytest.raises(GenerationError, match="different request"):
        list(
            iter_locus_chunks(
                other_request, REGISTRY, plan=plan, ephemeris=EPHEMERIS
            )
        )
    with pytest.raises(GenerationError, match="invalid chunk range"):
        list(
            iter_locus_chunks(
                request, REGISTRY, ephemeris=EPHEMERIS, start=3, stop=1
            )
        )


# ---------------------------------------------------------------------------
# Bounded-memory streaming export
# ---------------------------------------------------------------------------


def test_streamed_csv_is_byte_identical_to_batch(tmp_path: Path) -> None:
    request = make_request()
    result = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    batch_dir = tmp_path / "batch"
    write_products(result, batch_dir, generated_utc="2026-08-18T00:00:00Z")

    stream_dir = tmp_path / "stream"
    written = write_samples_stream(
        (
            chunk.corridor
            for chunk in iter_locus_chunks(request, REGISTRY, ephemeris=EPHEMERIS)
        ),
        stream_dir,
        calculation_id=result.calculation_id,
        model_id=request.model_id,
        result_warnings=result.warnings,
        rows_per_ecsv_part=7,  # force multiple parts
    )
    assert (stream_dir / "samples.csv").read_bytes() == (
        batch_dir / "samples.csv"
    ).read_bytes()
    # corridors.ecsv carries the same rows and metadata as the batch file.
    assert (stream_dir / "corridors.ecsv").read_bytes() == (
        batch_dir / "corridors.ecsv"
    ).read_bytes()

    from astropy.table import Table

    part_paths = sorted(
        path for label, path in written.items() if label.startswith("samples_ecsv_part")
    )
    assert len(part_paths) > 1  # 20 rows at 7 rows/part
    batch_table = Table.read(batch_dir / "samples.ecsv", format="ascii.ecsv")
    streamed_rows = 0
    sample_ids: list[str] = []
    for offset_expected, path in zip(
        range(0, len(batch_table), 7), part_paths, strict=True
    ):
        part = Table.read(path, format="ascii.ecsv")
        assert part.meta["calculation_id"] == result.calculation_id
        assert part.meta["part_row_offset"] == offset_expected
        streamed_rows += len(part)
        sample_ids.extend(str(v) for v in part["sample_id"])
    assert streamed_rows == len(batch_table)
    assert sample_ids == [str(v) for v in batch_table["sample_id"]]
