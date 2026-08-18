from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import GEOMETRY_MODEL_VERSION, __version__
from .config import Campaign, Target
from .geometry import GeometryEngine, ProbePoint
from .ledger import cell_is_complete, connect
from .partition import SearchCell, all_cells


@dataclass(frozen=True)
class PlannedTile:
    campaign_id: str
    tile_id: str
    target_id: str
    target_name: str
    role: str
    cell_ids: tuple[str, ...]
    cell_model_hashes: tuple[str, ...]
    z_near_au: float
    z_far_au: float
    best_time_utc: str
    window_start_utc: str
    window_end_utc: str
    visible: bool
    ra_icrs_deg: float
    dec_icrs_deg: float
    ra_cirs_deg: float
    dec_cirs_deg: float
    ra_icrs_hms: str
    dec_icrs_dms: str
    far_endpoint_ra_icrs_deg: float
    far_endpoint_dec_icrs_deg: float
    near_endpoint_ra_icrs_deg: float
    near_endpoint_dec_icrs_deg: float
    altitude_deg: float
    azimuth_deg: float
    sun_altitude_deg: float
    moon_separation_deg: float
    zone_radius_arcsec: float
    fov_usable_radius_arcsec: float
    rate_ra_cosdec_arcsec_per_hour: float
    rate_dec_arcsec_per_hour: float
    profile_id: str
    band: str
    signal_class: str
    telescope_id: str
    exposure_seconds: float
    geometry_model_version: str


@dataclass(frozen=True)
class PlanResult:
    tiles: tuple[PlannedTile, ...]
    total_cells: int
    completed_cells: int
    remaining_cells: int
    invisible_groups: int
    manifest: dict[str, Any]


def _stable_hash(value: Any, length: int = 16) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(blob).hexdigest()[:length]


def cell_model_hash(
    target: Target, cell: SearchCell, campaign: Campaign
) -> str:
    payload = {
        "geometry_model_version": GEOMETRY_MODEL_VERSION,
        "geometry_model": campaign.geometry_model,
        "ephemeris": campaign.ephemeris,
        "target": target.as_dict(),
        "cell": asdict(cell),
        # This width is part of what an observation claims to have searched.
        # A narrower historical search must not silently satisfy a wider model.
        "corridor_half_width_arcsec": (
            campaign.instrument.corridor_half_width_arcsec
        ),
    }
    return _stable_hash(payload, length=24)


def _time_grid(engine: GeometryEngine, campaign: Campaign) -> Any:
    u = engine.a["u"]
    start = engine.time(campaign.night.start_utc)
    end = engine.time(campaign.night.end_utc)
    if end <= start:
        raise ValueError("night.end_utc must be after night.start_utc.")
    duration_minutes = (end - start).to_value(u.min)
    count = max(2, int(math.floor(duration_minutes / campaign.night.grid_minutes)) + 1)
    offsets = np.linspace(0.0, duration_minutes, count) * u.min
    return start + offsets


def _find_best_time(
    engine: GeometryEngine,
    campaign: Campaign,
    target: Target,
    role: str,
    z_au: float,
    site_location: Any,
    times: Any,
) -> tuple[Any, Any, Any, bool, ProbePoint, Any]:
    u = engine.a["u"]
    valid: list[bool] = []
    points: list[ProbePoint] = []
    envs: list[Any] = []
    altitudes: list[float] = []
    for time in times:
        point = engine.probe_point(target, role, z_au, time, site_location)
        env = engine.environment(point, time, site_location)
        altitude = float(point.altaz.alt.to_value(u.deg))
        is_valid = (
            altitude >= campaign.constraints.min_altitude_deg
            and env.sun_altitude_deg <= campaign.constraints.max_sun_altitude_deg
            and env.moon_separation_deg >= campaign.constraints.min_moon_separation_deg
        )
        points.append(point)
        envs.append(env)
        altitudes.append(altitude)
        valid.append(is_valid)

    valid_indices = [index for index, value in enumerate(valid) if value]
    if valid_indices:
        best_index = max(valid_indices, key=lambda i: altitudes[i])
        visible = True
    else:
        best_index = max(range(len(altitudes)), key=lambda i: altitudes[i])
        visible = False

    left = best_index
    right = best_index
    if visible:
        while left > 0 and valid[left - 1]:
            left -= 1
        while right + 1 < len(valid) and valid[right + 1]:
            right += 1
    return (
        times[best_index],
        times[left],
        times[right],
        visible,
        points[best_index],
        envs[best_index],
    )


def _zone_for_cells(
    engine: GeometryEngine,
    campaign: Campaign,
    target: Target,
    role: str,
    cells: list[SearchCell],
    best_time: Any,
    site_location: Any,
) -> tuple[ProbePoint, float, tuple[ProbePoint, ...]]:
    u = engine.a["u"]
    q_lo = min(cell.q_lo_per_au for cell in cells)
    q_hi = max(cell.q_hi_per_au for cell in cells)
    center_z = 1.0 / (0.5 * (q_lo + q_hi))
    center = engine.probe_point(target, role, center_z, best_time, site_location)

    q_values = sorted(
        {
            q
            for cell in cells
            for q in (cell.q_lo_per_au, cell.q_mid_per_au, cell.q_hi_per_au)
        }
    )
    samples = tuple(
        engine.probe_point(target, role, 1.0 / q, best_time, site_location)
        for q in q_values
    )
    max_sep = max(
        center.geometric_icrs.separation(sample.geometric_icrs).to_value(u.arcsec)
        for sample in samples
    )
    rate_ra, rate_dec = engine.motion_rates(
        target, role, center_z, best_time, site_location
    )
    rate_total = math.hypot(rate_ra, rate_dec)
    motion_padding = rate_total * campaign.instrument.exposure_seconds / 7200.0
    radius = (
        max_sep
        + campaign.instrument.corridor_half_width_arcsec
        + motion_padding
    )
    return center, float(radius), samples


def _group_cells(
    engine: GeometryEngine,
    campaign: Campaign,
    target: Target,
    role: str,
    cells: list[SearchCell],
    best_time: Any,
    site_location: Any,
) -> list[list[SearchCell]]:
    sorted_cells = sorted(cells, key=lambda cell: cell.q_lo_per_au)
    groups: list[list[SearchCell]] = []
    current: list[SearchCell] = []
    max_radius = campaign.instrument.usable_radius_arcsec
    for cell in sorted_cells:
        candidate = current + [cell]
        _, radius, _ = _zone_for_cells(
            engine, campaign, target, role, candidate, best_time, site_location
        )
        if radius <= max_radius:
            current = candidate
            continue
        if not current:
            raise ValueError(
                f"Cell {cell.cell_id} needs a {radius:.1f}-arcsec zone, larger than "
                f"the usable FOV radius {max_radius:.1f} arcsec. Reduce "
                "partition.step_arcsec in the campaign configuration."
            )
        groups.append(current)
        current = [cell]
        _, radius, _ = _zone_for_cells(
            engine, campaign, target, role, current, best_time, site_location
        )
        if radius > max_radius:
            raise ValueError(
                f"Cell {cell.cell_id} cannot fit the usable FOV. Reduce the partition step."
            )
    if current:
        groups.append(current)
    return groups


def _format_time(value: Any) -> str:
    return str(value.utc.isot) + "Z"


def plan(
    targets: dict[str, Target],
    campaign: Campaign,
    ledger_path: str | Path,
) -> PlanResult:
    engine = GeometryEngine(
        ephemeris=campaign.ephemeris,
        iers_auto_download=campaign.iers_auto_download,
    )
    site_location = engine.site_location(campaign.site)
    times = _time_grid(engine, campaign)
    cells = all_cells(campaign.selections)
    unknown = sorted({cell.target_id for cell in cells} - set(targets))
    if unknown:
        raise ValueError(f"Campaign references unknown target IDs: {unknown}")

    model_hashes = {
        cell.cell_id: cell_model_hash(targets[cell.target_id], cell, campaign)
        for cell in cells
    }

    completed: set[str] = set()
    with connect(ledger_path) as conn:
        for cell in cells:
            if cell_is_complete(
                conn,
                cell_id=cell.cell_id,
                profile_id=campaign.profile.profile_id,
                model_hash=model_hashes[cell.cell_id],
                min_quality=campaign.profile.min_quality,
                required_visits=campaign.profile.required_successful_visits,
                min_visit_separation_days=campaign.profile.min_visit_separation_days,
            ):
                completed.add(cell.cell_id)

    remaining = [cell for cell in cells if cell.cell_id not in completed]
    by_target_role: dict[tuple[str, str], list[SearchCell]] = {}
    for cell in remaining:
        by_target_role.setdefault((cell.target_id, cell.role), []).append(cell)

    tiles: list[PlannedTile] = []
    invisible_groups = 0
    for (target_id, role), group_cells in sorted(
        by_target_role.items(),
        key=lambda item: (-targets[item[0][0]].priority, item[0][0], item[0][1]),
    ):
        target = targets[target_id]
        q_lo = min(cell.q_lo_per_au for cell in group_cells)
        q_hi = max(cell.q_hi_per_au for cell in group_cells)
        representative_z = 1.0 / (0.5 * (q_lo + q_hi))
        best_time, window_start, window_end, visible, _, _ = _find_best_time(
            engine,
            campaign,
            target,
            role,
            representative_z,
            site_location,
            times,
        )
        if not visible and not campaign.include_invisible:
            invisible_groups += 1
            continue

        tile_groups = _group_cells(
            engine,
            campaign,
            target,
            role,
            group_cells,
            best_time,
            site_location,
        )
        for tile_cells in tile_groups:
            center, zone_radius, zone_samples = _zone_for_cells(
                engine,
                campaign,
                target,
                role,
                tile_cells,
                best_time,
                site_location,
            )
            env = engine.environment(center, best_time, site_location)
            rate_ra, rate_dec = engine.motion_rates(
                target,
                role,
                center.heliocentric_range_au,
                best_time,
                site_location,
            )
            u = engine.a["u"]
            cell_ids = tuple(cell.cell_id for cell in tile_cells)
            cell_hashes = tuple(model_hashes[cell_id] for cell_id in cell_ids)
            tile_id = "tile-" + _stable_hash(
                {
                    "campaign": campaign.campaign_id,
                    "target": target_id,
                    "role": role,
                    "cells": cell_ids,
                },
                length=12,
            )
            tiles.append(
                PlannedTile(
                    campaign_id=campaign.campaign_id,
                    tile_id=tile_id,
                    target_id=target_id,
                    target_name=target.display_name,
                    role=role,
                    cell_ids=cell_ids,
                    cell_model_hashes=cell_hashes,
                    z_near_au=min(cell.z_near_au for cell in tile_cells),
                    z_far_au=max(cell.z_far_au for cell in tile_cells),
                    best_time_utc=_format_time(best_time),
                    window_start_utc=_format_time(window_start),
                    window_end_utc=_format_time(window_end),
                    visible=visible,
                    ra_icrs_deg=float(center.geometric_icrs.ra.to_value(u.deg)),
                    dec_icrs_deg=float(center.geometric_icrs.dec.to_value(u.deg)),
                    ra_cirs_deg=float(center.apparent_cirs.ra.to_value(u.deg)),
                    dec_cirs_deg=float(center.apparent_cirs.dec.to_value(u.deg)),
                    ra_icrs_hms=center.geometric_icrs.ra.to_string(
                        unit=u.hourangle, sep=":", precision=3, pad=True
                    ),
                    dec_icrs_dms=center.geometric_icrs.dec.to_string(
                        unit=u.deg, sep=":", precision=2, alwayssign=True, pad=True
                    ),
                    far_endpoint_ra_icrs_deg=float(
                        zone_samples[0].geometric_icrs.ra.to_value(u.deg)
                    ),
                    far_endpoint_dec_icrs_deg=float(
                        zone_samples[0].geometric_icrs.dec.to_value(u.deg)
                    ),
                    near_endpoint_ra_icrs_deg=float(
                        zone_samples[-1].geometric_icrs.ra.to_value(u.deg)
                    ),
                    near_endpoint_dec_icrs_deg=float(
                        zone_samples[-1].geometric_icrs.dec.to_value(u.deg)
                    ),
                    altitude_deg=float(center.altaz.alt.to_value(u.deg)),
                    azimuth_deg=float(center.altaz.az.to_value(u.deg)),
                    sun_altitude_deg=env.sun_altitude_deg,
                    moon_separation_deg=env.moon_separation_deg,
                    zone_radius_arcsec=zone_radius,
                    fov_usable_radius_arcsec=campaign.instrument.usable_radius_arcsec,
                    rate_ra_cosdec_arcsec_per_hour=rate_ra,
                    rate_dec_arcsec_per_hour=rate_dec,
                    profile_id=campaign.profile.profile_id,
                    band=campaign.profile.band,
                    signal_class=campaign.profile.signal_class,
                    telescope_id=campaign.instrument.telescope_id,
                    exposure_seconds=campaign.instrument.exposure_seconds,
                    geometry_model_version=GEOMETRY_MODEL_VERSION,
                )
            )

    tiles.sort(key=lambda tile: (tile.best_time_utc, -targets[tile.target_id].priority))
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "planner_version": __version__,
        "geometry_model_version": GEOMETRY_MODEL_VERSION,
        "campaign_id": campaign.campaign_id,
        "profile_id": campaign.profile.profile_id,
        "ephemeris": campaign.ephemeris,
        "total_cells": len(cells),
        "completed_cells": len(completed),
        "remaining_cells": len(remaining),
        "planned_tiles": len(tiles),
        "invisible_target_role_groups": invisible_groups,
        "campaign_hash": _stable_hash(asdict(campaign), length=24),
    }
    try:
        import astropy

        manifest["astropy_version"] = astropy.__version__
    except ImportError:
        pass
    manifest["numpy_version"] = np.__version__
    return PlanResult(
        tiles=tuple(tiles),
        total_cells=len(cells),
        completed_cells=len(completed),
        remaining_cells=len(remaining),
        invisible_groups=invisible_groups,
        manifest=manifest,
    )
