"""Result schema v3 (§3.5, roadmap item 10): provider identity on rows,
observation-interval time mode, VOTable output, manifest extensions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from astropy.table import Table
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris

from sglseti.config import load_request
from sglseti.crossings import find_crossings
from sglseti.errors import ConfigError
from sglseti.export import (
    RESULT_SCHEMA_VERSION,
    result_manifest,
    write_crossings_products,
    write_products,
)
from sglseti.generate import generate_loci, materialize_epochs
from sglseti.models import (
    AstrometricState,
    CrossingsRequest,
    EndpointKind,
    Epoch,
    GeometryRequest,
    LinkDirection,
    ObservationInterval,
    Observer,
    OutputFormat,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    Target,
    TimeInterval,
    TimeIntervals,
    TimeList,
    Validity,
)
from sglseti.providers import clear_provider_cache, resolve_target_state_provider
from sglseti.targets import TargetRegistry

EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
T_O = Time("2021-11-06T00:00:00", scale="utc")


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


REGISTRY = TargetRegistry.from_targets((make_target(),))


def make_request(**overrides: Any) -> GeometryRequest:
    values: dict = dict(
        target_ids=("synth",),
        roles=(Role.RX,),
        time=TimeList(epochs=(Epoch(epoch_id="e1", time=T_O),)),
        observer=Observer.earth_center(),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=3),
        model_id="tusay2022_eq5_7_v1",
        output_formats=(OutputFormat.ECSV, OutputFormat.CSV),
    )
    values.update(overrides)
    return GeometryRequest(**values)


# ---------------------------------------------------------------------------
# Provider identity on rows (§2.1 acceptance / §3.5)
# ---------------------------------------------------------------------------


def test_rows_identify_the_target_and_observer_providers() -> None:
    clear_provider_cache()
    result = generate_loci(make_request(), REGISTRY, ephemeris=EPHEMERIS)
    provider = resolve_target_state_provider(make_target())
    for sample in result.samples:
        assert sample.target_provider_id == "linear_astrometry_v1"
        assert sample.target_provider_version == provider.provider_version
        assert sample.target_provider_hash == provider.content_hash
        assert sample.observer_provider_id == "earth_center_v1"
        assert sample.observer_provider_hash.startswith("sha256:")


def test_invalid_rows_retain_provider_identity() -> None:
    clear_provider_cache()
    limited = FakeEphemeris(
        (0.004, -0.002, 0.001),
        (0.558, -0.744, -0.323),
        coverage_jd=(2400000.0, 2450000.0),  # excludes 2021
    )
    result = generate_loci(make_request(), REGISTRY, ephemeris=limited)
    assert result.samples
    for sample in result.samples:
        assert sample.validity is Validity.INVALID
        assert sample.target_provider_id == "linear_astrometry_v1"
        assert sample.observer_provider_id == "earth_center_v1"


def test_crossing_events_identify_providers() -> None:
    clear_provider_cache()
    request = CrossingsRequest(
        target_ids=("synth",),
        link_directions=(LinkDirection.INBOUND,),
        intervals=(TimeInterval(interval_id="i1", start=T_O, stop=T_O + 40.0),),
        observer=Observer.earth_center(),
        relay_distance_au=1000.0,
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=10.0,
    )
    result = find_crossings(request, REGISTRY, ephemeris=EPHEMERIS)
    assert result.events
    for event in result.events:
        assert event.target_provider_id == "linear_astrometry_v1"
        assert event.observer_provider_id == "earth_center_v1"
        assert event.target_provider_hash.startswith("sha256:")


# ---------------------------------------------------------------------------
# Observation-interval time mode (§3.1 batch integration)
# ---------------------------------------------------------------------------


def interval_spec() -> TimeIntervals:
    return TimeIntervals(
        intervals=(
            ObservationInterval(interval_id="exp-1", start=T_O, stop=T_O + 0.5),
            ObservationInterval(
                interval_id="exp-2",
                start=T_O + 1.0,
                stop=T_O + 1.0 + 3600.0 / 86400.0,
                subintegration_cadence_s=1200.0,
            ),
        )
    )


def test_intervals_materialize_with_labeled_epochs() -> None:
    epochs = materialize_epochs(interval_spec())
    ids = [epoch.epoch_id for epoch in epochs]
    assert ids[:3] == ["exp-1@start", "exp-1@mid", "exp-1@stop"]
    assert ids[3] == "exp-2@sub-0000"
    # 3600 s at a 1200 s cadence lands exactly on stop: four grid epochs,
    # no extra stop label.
    assert ids[-1] == "exp-2@sub-0003"
    assert len(ids) == 7
    assert epochs[0].interval_id == "exp-1"
    assert epochs[0].interval_phase == "start"
    assert epochs[0].interval_duration_s == pytest.approx(43200.0)


def test_interval_rows_carry_interval_semantics() -> None:
    clear_provider_cache()
    request = make_request(time=interval_spec())
    result = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    by_epoch = {s.epoch_id: s for s in result.samples}
    sample = by_epoch["exp-1@mid"]
    assert sample.interval_id == "exp-1"
    assert sample.interval_phase == "mid"
    assert sample.interval_duration_s == pytest.approx(43200.0)
    # Point-epoch rows stay None.
    point = generate_loci(make_request(), REGISTRY, ephemeris=EPHEMERIS)
    assert point.samples[0].interval_id is None


def test_request_yaml_intervals_mode(tmp_path: Path) -> None:
    data: dict[str, Any] = {
        "schema_version": 1,
        "targets": ["barnard"],
        "roles": ["rx"],
        "time": {
            "intervals": [
                {
                    "id": "exp-1",
                    "start_utc": "2015-09-04T23:30:00Z",
                    "stop_utc": "2015-09-05T10:13:00Z",
                },
                {
                    "id": "exp-2",
                    "start_utc": "2019-09-05T00:00:00Z",
                    "stop_utc": "2019-09-05T01:00:00Z",
                    "subintegration_cadence_s": 900.0,
                },
            ]
        },
        "observer": {"kind": "earth_center"},
        "relay_range": {
            "min_au": 550.0,
            "max_au": 2500.0,
            "sampling": {"kind": "count", "count": 5},
        },
        "model": {"id": "tusay2022_eq5_7_v1"},
    }
    path = tmp_path / "request.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    request = load_request(path)
    assert isinstance(request.time, TimeIntervals)
    assert request.time.intervals[1].subintegration_cadence_s == 900.0
    bad = dict(data)
    bad["time"] = {"intervals": [{"id": "x", "start_utc": "2020-01-01T00:00:00Z"}]}
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ConfigError, match="stop_utc"):
        load_request(path)


# ---------------------------------------------------------------------------
# VOTable output and manifest extensions
# ---------------------------------------------------------------------------


def test_votable_products(tmp_path: Path) -> None:
    clear_provider_cache()
    request = make_request(output_formats=(OutputFormat.ECSV, OutputFormat.VOTABLE))
    result = generate_loci(request, REGISTRY, ephemeris=EPHEMERIS)
    written = write_products(result, tmp_path, generated_utc="2026-08-18T00:00:00Z")
    votable = Table.read(written["samples_votable"], format="votable")
    assert len(votable) == len(result.samples)
    assert str(votable["target_provider_id"][0]) == "linear_astrometry_v1"
    assert votable["icrs_ra_deg"].unit is not None

    crossings_request = CrossingsRequest(
        target_ids=("synth",),
        link_directions=(LinkDirection.INBOUND,),
        intervals=(TimeInterval(interval_id="i1", start=T_O, stop=T_O + 40.0),),
        observer=Observer.earth_center(),
        relay_distance_au=1000.0,
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=10.0,
        output_formats=(OutputFormat.ECSV, OutputFormat.VOTABLE),
    )
    crossings = find_crossings(crossings_request, REGISTRY, ephemeris=EPHEMERIS)
    crossings_written = write_crossings_products(
        crossings, tmp_path / "xng", generated_utc="2026-08-18T00:00:00Z"
    )
    events_votable = Table.read(crossings_written["events_votable"], format="votable")
    assert len(events_votable) == len(crossings.events)


def test_manifest_extensions() -> None:
    clear_provider_cache()
    result = generate_loci(make_request(time=interval_spec()), REGISTRY, ephemeris=EPHEMERIS)
    manifest = result_manifest(
        result,
        generated_utc="2026-08-18T00:00:00Z",
        input_file_hashes={},
        output_files={},
        source_revision="deadbeef",
    )
    science = manifest["science_inputs"]
    assert science["result_schema_version"] == RESULT_SCHEMA_VERSION == 3
    providers = science["target_state_providers"]
    assert providers["synth"]["provider_id"] == "linear_astrometry_v1"
    assert providers["synth"]["content_hash"].startswith("sha256:")
    assert science["observer_state_providers"]["earth-center"]["provider_id"] == "earth_center_v1"
    assert science["uncertainty"]["method"] == "not_propagated"
    assert "observation_intervals" in science["time_semantics"]
    run = manifest["run"]
    assert run["source_revision"] == "deadbeef"
    assert run["versions"]["sglseti"]
