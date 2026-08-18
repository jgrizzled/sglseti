"""ECSV/JSON/CSV/DS9 writers and the provenance manifest.

All products come from the same typed result objects; exporters never
recalculate geometry (this module imports no geometry, ephemeris, or
generation code). Column order is the dataclass field order of the result
records — deterministic and covered by golden-header tests.

Formats (PRD §9.5):
- ECSV: canonical tabular output, with units and table-level metadata;
- JSON: lossless document under ``RESULT_SCHEMA_VERSION`` (NaN → null);
- CSV: convenience view; field names carry explicit unit suffixes;
- DS9: corridor polylines and width circles, pointing circles, fk5 frame.
  Region widths are the request's *assumed* half-width — request validation
  refuses DS9 without one, so no region ever carries an unlabeled width.

Every file-producing CLI command also writes ``manifest.json``
(:func:`result_manifest`): the deterministic science identity (request,
model, target and resource hashes) is hashed separately from run metadata
(timestamp, output files, library versions), which never affects the
science hash.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from .models import (
    BeamWindow,
    CalculationResult,
    Corridor,
    CrossingEvent,
    CrossingsResult,
    LocusSample,
    OutputFormat,
    Pointing,
    VisibilitySample,
)
from .provenance import build_manifest, canonicalize, file_sha256

__all__ = [
    "CROSSINGS_RESULT_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "crossings_manifest",
    "result_manifest",
    "write_crossings_products",
    "write_products",
]

RESULT_SCHEMA_VERSION = 2

#: Crossing event/window products carry their own schema counter.
CROSSINGS_RESULT_SCHEMA_VERSION = 1

#: Fixed coordinate/time conventions recorded in every manifest (PRD §9.4).
CONVENTIONS = {
    "geometric_frame": "icrs barycentric line of sight from the stated observer",
    "apparent_frames": "cirs (topocentric for sites) and altaz, refraction disabled",
    "time_scales": "utc for timestamps, tdb julian dates for computation epochs",
    "catalog_epoch_semantics": "ssb_light_arrival_time",
    "angles": "degrees; rates in arcsec/hour; distances in au",
}

_UNIT_SUFFIXES = (
    ("_ra_deg", "deg"),
    ("_dec_deg", "deg"),
    ("_alt_deg", "deg"),
    ("_az_deg", "deg"),
    ("_separation_deg", "deg"),
    ("_altitude_deg", "deg"),
    ("_arcsec_per_hr", "arcsec / h"),
    ("_arcsec", "arcsec"),
    ("_tdb_jd", "d"),
    ("_days", "d"),
    ("_au", "AU"),
    ("_per_au", "1 / AU"),
    ("_km_s", "km / s"),
    ("_km", "km"),
    ("_solar_radii", "solRad"),
)

_SAMPLE_FIELDS = tuple(f.name for f in dataclasses.fields(LocusSample))
SAMPLE_COLUMNS = ("corridor_id", *_SAMPLE_FIELDS)
CORRIDOR_COLUMNS = (
    *(f.name for f in dataclasses.fields(Corridor) if f.name != "samples"),
    "sample_count",
    "sample_ids",
)
VISIBILITY_COLUMNS = tuple(f.name for f in dataclasses.fields(VisibilitySample))
POINTING_COLUMNS = tuple(f.name for f in dataclasses.fields(Pointing))
EVENT_COLUMNS = (
    *(f.name for f in dataclasses.fields(CrossingEvent) if f.name != "windows"),
    "window_count",
)
WINDOW_COLUMNS = tuple(f.name for f in dataclasses.fields(BeamWindow))


def write_products(
    result: CalculationResult,
    output_dir: str | Path,
    *,
    generated_utc: str,
    input_file_hashes: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Write every requested format plus ``manifest.json``.

    Returns a label -> path mapping of everything written. ``generated_utc``
    is supplied by the caller (it is run metadata, never science identity).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    formats = set(result.request.output_formats)
    written: dict[str, Path] = {}

    corridor_by_sample = _corridor_index(result)
    sample_rows = [
        _record_row(sample, corridor_id=corridor_by_sample[id(sample)])
        for corridor in result.corridors
        for sample in corridor.samples
    ]
    corridor_rows = [_corridor_row(corridor) for corridor in result.corridors]
    visibility_rows = [_record_row(v) for v in result.visibility]
    pointing_rows = [_record_row(p) for p in result.pointings]

    meta = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "calculation_id": result.calculation_id,
        "model_id": result.request.model_id,
        "warnings": list(result.warnings),
    }
    if OutputFormat.ECSV in formats:
        written["samples_ecsv"] = _write_ecsv(
            output_dir / "samples.ecsv", SAMPLE_COLUMNS, sample_rows, meta
        )
        written["corridors_ecsv"] = _write_ecsv(
            output_dir / "corridors.ecsv", CORRIDOR_COLUMNS, corridor_rows, meta
        )
        if visibility_rows:
            written["visibility_ecsv"] = _write_ecsv(
                output_dir / "visibility.ecsv", VISIBILITY_COLUMNS, visibility_rows, meta
            )
        if pointing_rows:
            written["pointings_ecsv"] = _write_ecsv(
                output_dir / "pointings.ecsv", POINTING_COLUMNS, pointing_rows, meta
            )
    if OutputFormat.JSON in formats:
        written["result_json"] = _write_json(output_dir / "result.json", result)
    if OutputFormat.CSV in formats:
        written["samples_csv"] = _write_csv(
            output_dir / "samples.csv", SAMPLE_COLUMNS, sample_rows
        )
        if pointing_rows:
            written["pointings_csv"] = _write_csv(
                output_dir / "pointings.csv", POINTING_COLUMNS, pointing_rows
            )
    if OutputFormat.DS9 in formats:
        written["regions_ds9"] = _write_ds9(output_dir / "regions.ds9", result)

    manifest = result_manifest(
        result,
        generated_utc=generated_utc,
        input_file_hashes=input_file_hashes or {},
        output_files={label: file_sha256(path) for label, path in written.items()},
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    written["manifest_json"] = manifest_path
    return written


def result_manifest(
    result: CalculationResult,
    *,
    generated_utc: str,
    input_file_hashes: Mapping[str, str],
    output_files: Mapping[str, str],
) -> dict[str, Any]:
    """Manifest with the science identity hashed apart from run metadata."""
    science: dict[str, Any] = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "calculation_id": result.calculation_id,
        "request": _canonical_request(result),
        "model_id": result.request.model_id,
        "model_versions": sorted({s.model_version for s in result.samples}),
        "target_source_hashes": {
            target_id: source_hash
            for target_id, source_hash in sorted(
                {(s.target_id, s.target_source_hash) for s in result.samples}
            )
        },
        "ephemeris_ids": sorted({s.ephemeris_id for s in result.samples}),
        "iers_id": result.iers_id,
        "input_file_hashes": dict(sorted(input_file_hashes.items())),
        "conventions": CONVENTIONS,
    }
    run = {
        "generated_utc": generated_utc,
        "output_files": dict(sorted(output_files.items())),
        "warning_summary": list(result.warnings),
        "sample_count": len(result.samples),
        "corridor_count": len(result.corridors),
        "visibility_count": len(result.visibility),
        "pointing_count": len(result.pointings),
        "versions": _versions(),
    }
    manifest = build_manifest(science_inputs=science, run_metadata=run)
    return manifest


def write_crossings_products(
    result: CrossingsResult,
    output_dir: str | Path,
    *,
    generated_utc: str,
    input_file_hashes: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Write every requested crossings format plus ``manifest.json``.

    Products are the events table (one row per impact-parameter minimum or
    invalid status row) and the windows table (one row per assumed beam
    radius per event, joined by ``event_id``). Returns a label -> path
    mapping of everything written.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    formats = set(result.request.output_formats)
    written: dict[str, Path] = {}

    event_rows = [
        _record_row(event, window_count=len(event.windows)) for event in result.events
    ]
    window_rows = [
        _record_row(window) for event in result.events for window in event.windows
    ]

    meta = {
        "crossings_result_schema_version": CROSSINGS_RESULT_SCHEMA_VERSION,
        "crossings_id": result.crossings_id,
        "model_id": result.request.model_id,
        "warnings": list(result.warnings),
    }
    if OutputFormat.ECSV in formats:
        written["events_ecsv"] = _write_ecsv(
            output_dir / "events.ecsv", EVENT_COLUMNS, event_rows, meta
        )
        written["windows_ecsv"] = _write_ecsv(
            output_dir / "windows.ecsv", WINDOW_COLUMNS, window_rows, meta
        )
    if OutputFormat.JSON in formats:
        written["result_json"] = _write_crossings_json(
            output_dir / "result.json", result, event_rows, window_rows
        )
    if OutputFormat.CSV in formats:
        written["events_csv"] = _write_csv(
            output_dir / "events.csv", EVENT_COLUMNS, event_rows
        )
        written["windows_csv"] = _write_csv(
            output_dir / "windows.csv", WINDOW_COLUMNS, window_rows
        )

    manifest = crossings_manifest(
        result,
        generated_utc=generated_utc,
        input_file_hashes=input_file_hashes or {},
        output_files={label: file_sha256(path) for label, path in written.items()},
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    written["manifest_json"] = manifest_path
    return written


def crossings_manifest(
    result: CrossingsResult,
    *,
    generated_utc: str,
    input_file_hashes: Mapping[str, str],
    output_files: Mapping[str, str],
) -> dict[str, Any]:
    """Crossings manifest with science identity hashed apart from run data."""
    axis_models = sorted(
        {(e.axis_model_id, e.axis_model_version) for e in result.events}
    )
    science: dict[str, Any] = {
        "crossings_result_schema_version": CROSSINGS_RESULT_SCHEMA_VERSION,
        "crossings_id": result.crossings_id,
        "request": _canonical_crossings_request(result),
        "axis_models": [list(pair) for pair in axis_models],
        "model_id": result.request.model_id,
        "model_versions": sorted({e.model_version for e in result.events}),
        "target_source_hashes": {
            target_id: source_hash
            for target_id, source_hash in sorted(
                {(e.target_id, e.target_source_hash) for e in result.events}
            )
        },
        "ephemeris_ids": sorted({e.ephemeris_id for e in result.events}),
        "input_file_hashes": dict(sorted(input_file_hashes.items())),
        "conventions": CONVENTIONS,
    }
    run = {
        "generated_utc": generated_utc,
        "output_files": dict(sorted(output_files.items())),
        "warning_summary": list(result.warnings),
        "event_count": len(result.events),
        "window_count": sum(len(e.windows) for e in result.events),
        "versions": _versions(),
    }
    return build_manifest(science_inputs=science, run_metadata=run)


def _canonical_crossings_request(result: CrossingsResult) -> Any:
    canonical = canonicalize(result.request)
    # Content identity, never location (matches crossings_id handling).
    ephemeris_ids = sorted({e.ephemeris_id for e in result.events})
    canonical["fields"]["ephemeris"] = (
        ephemeris_ids[0] if len(ephemeris_ids) == 1 else ephemeris_ids
    )
    return canonical


def _write_crossings_json(
    path: Path,
    result: CrossingsResult,
    event_rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
) -> Path:
    document = {
        "crossings_result_schema_version": CROSSINGS_RESULT_SCHEMA_VERSION,
        "crossings_id": result.crossings_id,
        "request": _canonical_crossings_request(result),
        "warnings": list(result.warnings),
        "events": [_json_safe(row) for row in event_rows],
        "windows": [_json_safe(row) for row in window_rows],
    }
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _versions() -> dict[str, str]:
    import platform
    from importlib.metadata import PackageNotFoundError, version

    versions = {"python": platform.python_version()}
    for package in ("sglseti", "astropy", "astropy-iers-data", "numpy", "pyerfa"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:  # pragma: no cover
            versions[package] = "unknown"
    return versions


def _canonical_request(result: CalculationResult) -> Any:
    canonical = canonicalize(result.request)
    # Content identity, never location (matches calculation_id handling).
    ephemeris_ids = sorted({s.ephemeris_id for s in result.samples})
    canonical["fields"]["ephemeris"] = (
        ephemeris_ids[0] if len(ephemeris_ids) == 1 else ephemeris_ids
    )
    canonical["fields"]["iers"] = result.iers_id
    return canonical


def _corridor_index(result: CalculationResult) -> dict[int, str]:
    return {
        id(sample): corridor.corridor_id
        for corridor in result.corridors
        for sample in corridor.samples
    }


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return ";".join(str(_plain(item)) for item in value)
    return value


def _record_row(record: Any, **extra: Any) -> dict[str, Any]:
    row = {**extra}
    for field in dataclasses.fields(record):
        if field.name in ("samples", "windows"):
            continue
        row[field.name] = _plain(getattr(record, field.name))
    return row


def _corridor_row(corridor: Corridor) -> dict[str, Any]:
    row = _record_row(corridor)
    row["sample_count"] = len(corridor.samples)
    row["sample_ids"] = ";".join(sample.sample_id for sample in corridor.samples)
    return row


def _column_unit(name: str) -> str | None:
    for suffix, unit in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return None


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_ecsv(
    path: Path,
    columns: Sequence[str],
    rows: list[dict[str, Any]],
    meta: Mapping[str, Any],
) -> Path:
    from astropy.table import Table

    data: dict[str, list[Any]] = {
        column: [_ecsv_cell(row.get(column)) for row in rows] for column in columns
    }
    table = Table(data=data, names=list(columns))
    for column in columns:
        unit = _column_unit(column)
        if unit is not None and len(rows):
            table[column].unit = unit
    table.meta.update(meta)
    table.write(path, format="ascii.ecsv", overwrite=True)
    return path


def _ecsv_cell(value: Any) -> Any:
    if value is None:
        return math.nan
    return value


def _write_csv(path: Path, columns: Sequence[str], rows: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {c: ("" if row.get(c) is None else row.get(c)) for c in columns}
            )
    return path


def _write_json(path: Path, result: CalculationResult) -> Path:
    corridor_by_sample = _corridor_index(result)
    document = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "calculation_id": result.calculation_id,
        "request": _canonical_request(result),
        "warnings": list(result.warnings),
        "samples": [
            _json_safe(_record_row(s, corridor_id=corridor_by_sample[id(s)]))
            for c in result.corridors
            for s in c.samples
        ],
        "corridors": [_json_safe(_corridor_row(c)) for c in result.corridors],
        "visibility": [_json_safe(_record_row(v)) for v in result.visibility],
        "pointings": [_json_safe(_record_row(p)) for p in result.pointings],
    }
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _json_safe(row: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, float) and not math.isfinite(value):
            safe[key] = None
        else:
            safe[key] = value
    return safe


def _write_ds9(path: Path, result: CalculationResult) -> Path:
    """Corridor polylines + assumed-width circles, and pointing circles.

    Non-operational samples (invalid validity or non-finite coordinates) are
    skipped and counted in the header comment so their absence is visible.
    """
    half_width = result.request.assumed_half_width_arcsec
    assert half_width is not None  # request validation guarantees this
    lines = [
        "# Region file format: DS9 version 4.1",
        f"# sglseti calculation {result.calculation_id}",
        f"# widths are ASSUMED half-widths ({half_width} arcsec), not covariance",
        "global color=green width=1",
        "fk5",
    ]
    skipped = 0
    for corridor in result.corridors:
        valid = [s for s in corridor.samples if s.is_operational]
        skipped += len(corridor.samples) - len(valid)
        for sample in valid:
            lines.append(
                f"circle({sample.icrs_ra_deg:.9f},{sample.icrs_dec_deg:.9f},"
                f'{half_width:g}") # tag={{{corridor.corridor_id}}} '
                f"text={{{sample.sample_id}}}"
            )
        for first, second in zip(valid[:-1], valid[1:], strict=False):
            lines.append(
                f"line({first.icrs_ra_deg:.9f},{first.icrs_dec_deg:.9f},"
                f"{second.icrs_ra_deg:.9f},{second.icrs_dec_deg:.9f}) "
                f"# tag={{{corridor.corridor_id}}}"
            )
    for pointing in result.pointings:
        lines.append(
            f"circle({pointing.center_icrs_ra_deg:.9f},"
            f"{pointing.center_icrs_dec_deg:.9f},{pointing.radius_arcsec:g}\") "
            f"# color=cyan tag={{{pointing.pointing_id}}} "
            f"text={{{pointing.target_id}/{pointing.role.value}}}"
        )
    if skipped:
        lines.insert(2, f"# {skipped} invalid sample(s) omitted")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
