from __future__ import annotations

from dataclasses import asdict
import csv
import json
from pathlib import Path
from typing import Iterable

from .planner import PlanResult, PlannedTile


CSV_FIELDS = [
    "campaign_id",
    "tile_id",
    "target_id",
    "target_name",
    "role",
    "cell_ids",
    "cell_model_hashes",
    "z_near_au",
    "z_far_au",
    "best_time_utc",
    "window_start_utc",
    "window_end_utc",
    "visible",
    "ra_icrs_deg",
    "dec_icrs_deg",
    "ra_cirs_deg",
    "dec_cirs_deg",
    "ra_icrs_hms",
    "dec_icrs_dms",
    "far_endpoint_ra_icrs_deg",
    "far_endpoint_dec_icrs_deg",
    "near_endpoint_ra_icrs_deg",
    "near_endpoint_dec_icrs_deg",
    "altitude_deg",
    "azimuth_deg",
    "sun_altitude_deg",
    "moon_separation_deg",
    "zone_radius_arcsec",
    "fov_usable_radius_arcsec",
    "rate_ra_cosdec_arcsec_per_hour",
    "rate_dec_arcsec_per_hour",
    "profile_id",
    "band",
    "signal_class",
    "telescope_id",
    "exposure_seconds",
    "geometry_model_version",
]


def _tile_row(tile: PlannedTile) -> dict[str, object]:
    row = asdict(tile)
    row["cell_ids"] = ";".join(tile.cell_ids)
    row["cell_model_hashes"] = ";".join(tile.cell_model_hashes)
    return row


def write_plan_csv(path: str | Path, tiles: Iterable[PlannedTile]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for tile in tiles:
            writer.writerow(_tile_row(tile))


def write_results_template(path: str | Path, tiles: Iterable[PlannedTile]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "tile_id",
        "observed_start_utc",
        "observed_end_utc",
        "status",
        "quality",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for tile in tiles:
            writer.writerow(
                {
                    "tile_id": tile.tile_id,
                    "observed_start_utc": "",
                    "observed_end_utc": "",
                    "status": "",
                    "quality": "",
                    "notes": "",
                }
            )


def write_ds9_regions(path: str | Path, tiles: Iterable[PlannedTile]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Region file format: DS9 version 4.1",
        'global color=green dashlist=8 3 width=1 font="helvetica 10 normal roman"',
        "icrs",
    ]
    for tile in tiles:
        text = f"{tile.tile_id} {tile.target_id} {tile.role} {tile.z_near_au:.0f}-{tile.z_far_au:.0f}AU"
        lines.append(
            f'circle({tile.ra_icrs_deg:.10f},{tile.dec_icrs_deg:.10f},'
            f'{tile.zone_radius_arcsec:.3f}") # color=green text={{{text} zone}}'
        )
        lines.append(
            f'circle({tile.ra_icrs_deg:.10f},{tile.dec_icrs_deg:.10f},'
            f'{tile.fov_usable_radius_arcsec:.3f}") # color=cyan dash=1 text={{{text} usable-FOV}}'
        )
        lines.append(
            f'line({tile.far_endpoint_ra_icrs_deg:.10f},'
            f'{tile.far_endpoint_dec_icrs_deg:.10f},'
            f'{tile.near_endpoint_ra_icrs_deg:.10f},'
            f'{tile.near_endpoint_dec_icrs_deg:.10f}) # color=yellow'
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: str | Path, result: PlanResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_all(output_dir: str | Path, result: PlanResult) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "pointings": output_dir / "pointings.csv",
        "regions": output_dir / "pointings.reg",
        "results_template": output_dir / "observation_results_template.csv",
        "manifest": output_dir / "manifest.json",
    }
    write_plan_csv(files["pointings"], result.tiles)
    write_ds9_regions(files["regions"], result.tiles)
    write_results_template(files["results_template"], result.tiles)
    write_manifest(files["manifest"], result)
    return files
