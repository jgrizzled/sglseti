"""Crossings product files: golden columns, formats, manifest identity."""

from __future__ import annotations

import json
from pathlib import Path

from test_crossings import (
    JD0,
    CircularOrbitEphemeris,
    make_request,
    make_target,
    run,
)

from sglseti.export import (
    CROSSINGS_RESULT_SCHEMA_VERSION,
    EVENT_COLUMNS,
    WINDOW_COLUMNS,
    write_crossings_products,
)
from sglseti.models import OutputFormat

# Golden column tuples: any change is a result-schema change and must be a
# deliberate, versioned decision.
EXPECTED_EVENT_COLUMNS = (
    "crossings_id",
    "event_id",
    "target_id",
    "link_direction",
    "interval_id",
    "minimum_index",
    "observer_id",
    "t_ca_utc",
    "t_ca_tdb_jd",
    "catalog_direction_epoch_tdb_jd",
    "b_min_au",
    "b_min_km",
    "b_min_solar_radii",
    "axis_distance_au",
    "v_perp_km_s",
    "axis_icrs_ra_deg",
    "axis_icrs_dec_deg",
    "star_icrs_ra_deg",
    "star_icrs_dec_deg",
    "relay_icrs_ra_deg",
    "relay_icrs_dec_deg",
    "z_au",
    "target_light_time_days",
    "role",
    "axis_model_id",
    "axis_model_version",
    "model_id",
    "model_version",
    "target_source_hash",
    "ephemeris_id",
    "target_provider_id",
    "target_provider_version",
    "target_provider_hash",
    "observer_provider_id",
    "observer_provider_version",
    "observer_provider_hash",
    "validity",
    "uncertainty_method",
    "side",
    "warnings",
    "window_count",
)
EXPECTED_WINDOW_COLUMNS = (
    "window_id",
    "event_id",
    "beam_radius_au",
    "ingress_utc",
    "egress_utc",
    "ingress_tdb_jd",
    "egress_tdb_jd",
    "duration_days",
    "truncated_ingress",
    "truncated_egress",
)


def test_golden_columns() -> None:
    assert EVENT_COLUMNS == EXPECTED_EVENT_COLUMNS
    assert WINDOW_COLUMNS == EXPECTED_WINDOW_COLUMNS


def build_result(**request_overrides: object):
    return run(
        make_request(beam_radii_au=(0.05, 0.2), **request_overrides),
        make_target(),
    )


def test_products_round_trip(tmp_path: Path) -> None:
    result = build_result(output_formats=(OutputFormat.ECSV, OutputFormat.JSON, OutputFormat.CSV))
    written = write_crossings_products(result, tmp_path, generated_utc="2026-08-18T00:00:00+00:00")
    assert set(written) == {
        "events_ecsv",
        "windows_ecsv",
        "events_csv",
        "windows_csv",
        "result_json",
        "manifest_json",
    }

    from astropy.table import Table

    events = Table.read(written["events_ecsv"])
    assert tuple(events.colnames) == EXPECTED_EVENT_COLUMNS
    assert len(events) == 2
    assert events["b_min_au"].unit == "AU"
    assert events["v_perp_km_s"].unit == "km / s"
    assert events.meta["crossings_id"] == result.crossings_id
    assert events.meta["crossings_result_schema_version"] == CROSSINGS_RESULT_SCHEMA_VERSION

    windows = Table.read(written["windows_ecsv"])
    assert tuple(windows.colnames) == EXPECTED_WINDOW_COLUMNS
    assert len(windows) == 4
    assert set(windows["event_id"]) == set(events["event_id"])

    document = json.loads(written["result_json"].read_text(encoding="utf-8"))
    assert document["crossings_id"] == result.crossings_id
    assert len(document["events"]) == 2
    assert len(document["windows"]) == 4
    # Content identity, never location, in the canonical request.
    assert document["request"]["fields"]["ephemeris"] == "fake_circular_orbit"

    with written["events_csv"].open(encoding="utf-8") as handle:
        header = handle.readline().strip()
    assert header == ",".join(EXPECTED_EVENT_COLUMNS)

    manifest = json.loads(written["manifest_json"].read_text(encoding="utf-8"))
    science = manifest["science_inputs"]
    assert science["crossings_id"] == result.crossings_id
    assert science["axis_models"] == [["sun_star_axis_v1", "1.0.0"]]
    assert science["ephemeris_ids"] == ["fake_circular_orbit"]
    assert manifest["run"]["event_count"] == 2
    assert manifest["run"]["window_count"] == 4
    assert manifest["run"]["generated_utc"] == "2026-08-18T00:00:00+00:00"


def test_manifest_science_hash_ignores_run_metadata(tmp_path: Path) -> None:
    result = build_result()
    first = write_crossings_products(
        result, tmp_path / "a", generated_utc="2026-08-18T00:00:00+00:00"
    )
    second = write_crossings_products(
        result, tmp_path / "b", generated_utc="2027-01-01T00:00:00+00:00"
    )
    manifest_a = json.loads(first["manifest_json"].read_text(encoding="utf-8"))
    manifest_b = json.loads(second["manifest_json"].read_text(encoding="utf-8"))
    assert manifest_a["science_input_hash"] == manifest_b["science_input_hash"]
    assert manifest_a["run"] != manifest_b["run"]


def test_invalid_status_row_exports(tmp_path: Path) -> None:
    from sglseti.crossings import find_crossings
    from sglseti.targets import TargetRegistry

    registry = TargetRegistry.from_targets((make_target(),))
    result = find_crossings(
        make_request(),
        registry,
        ephemeris=CircularOrbitEphemeris(coverage_jd=(JD0, JD0 + 100.0)),
    )
    written = write_crossings_products(result, tmp_path, generated_utc="2026-08-18T00:00:00+00:00")
    document = json.loads(written["result_json"].read_text(encoding="utf-8"))
    (event,) = document["events"]
    # NaN geometry becomes null; the unknown side is null, never a label.
    assert event["b_min_au"] is None
    assert event["side"] is None
    assert event["validity"] == "invalid"
    assert document["windows"] == []
