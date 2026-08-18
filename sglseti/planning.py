"""Conservative circular-FOV grouping and stateless commensal planning.

:func:`plan_commensal` turns a generated :class:`CalculationResult` into the
same result plus visibility samples and candidate pointings. It is a
complete, stateless function of the request and resources: no ledger, no
completion state, no profile — every eligible pointing is returned, ordered
by target priority then epoch, and nothing here is a schedule.

Grouping (ported from the prototype's greedy adjacent grouping, coverage
semantics removed): within one corridor, adjacent relay segments are merged
while the conservative zone still fits the usable field radius. The zone
radius keeps its components separate:

    radius = track_extent + assumed_half_width + motion_padding
             + window_drift

where ``track_extent`` is the maximal angular distance from the zone center
(spherical midpoint of the group's extreme interval boundaries) to any
covered point — each sample's representative coordinate and its segment's
near/far boundary coordinates, so the footprint covers the relay-distance
*intervals* the samples represent, not just their midpoints —
``assumed_half_width`` is the request's explicitly assumed corridor
half-width (never covariance), and ``motion_padding`` is half an exposure of
the fastest covered rate (representative and near-boundary rates; the near
boundary is the interval's fastest point; only when ``fov.exposure_s`` is
configured), and ``window_drift`` is the extra extent the grouped segments
sweep across the advertised window's grid epochs beyond the
representative-epoch track — the pointing covers the window it advertises,
not just one instant. Endpoint coverage suffices for this model because the
corridor is the sky projection of a near-straight ray: direction moves
monotonically along its arc with z, and each segment's interior
representative is evaluated as well. A group that exceeds the usable radius
even as a single segment is still emitted, flagged
``group_exceeds_usable_fov`` — pointings are candidate zones, and hiding
the segment would misstate coverage of the hypothesis space.

Visibility for a corridor reports the middle operational segment's line of
sight, while its pass/fail verdict also probes the corridor's angular
extreme points, so an endpoint cannot silently fail a threshold the middle
sample meets. Samples whose ``validity`` is invalid never enter visibility,
grouping, or pointings, even when they carry finite diagnostic coordinates;
degraded conditions (``below_solar_focal_minimum``,
``outside_search_prior``) stay consumable and are surfaced on any pointing
built from them.
"""

from __future__ import annotations

import dataclasses
import math

from .ephemeris import AstropyEphemeris, Ephemeris, IersResource
from .errors import PlanningError
from .generate import materialize_epochs
from .geometry import WARN_BELOW_FOCAL, WARN_OUTSIDE_SEARCH_PRIOR
from .models import (
    CalculationResult,
    Corridor,
    LocusSample,
    ObserverKind,
    Pointing,
    Role,
    VisibilitySample,
)
from .observability import VisibilityWindow, find_windows, visibility_sample
from .provenance import stable_id
from .targets import TargetRegistry

__all__ = [
    "WARN_GROUP_EXCEEDS_FOV",
    "WARN_NO_OPERATIONAL_SAMPLES",
    "WARN_NO_VISIBLE_WINDOW",
    "group_corridor_samples",
    "plan_commensal",
]

WARN_GROUP_EXCEEDS_FOV = "group_exceeds_usable_fov"
WARN_NO_OPERATIONAL_SAMPLES = "no_operational_samples"
WARN_NO_VISIBLE_WINDOW = "no_visible_window"

_ARCSEC = 3600.0


def _unit(ra_deg: float, dec_deg: float) -> tuple[float, float, float]:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return (
        math.cos(dec) * math.cos(ra),
        math.cos(dec) * math.sin(ra),
        math.sin(dec),
    )


def _radec(v: tuple[float, float, float]) -> tuple[float, float]:
    norm = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    ra = math.degrees(math.atan2(v[1], v[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, v[2] / norm))))
    return ra, dec


def _separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a, b = _unit(ra1, dec1), _unit(ra2, dec2)
    cross = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    sin_sep = math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
    cos_sep = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    return math.degrees(math.atan2(sin_sep, cos_sep)) * _ARCSEC


@dataclasses.dataclass(frozen=True)
class _Zone:
    center_ra_deg: float
    center_dec_deg: float
    track_extent_arcsec: float
    motion_padding_arcsec: float
    radius_arcsec: float


def _boundary_or_rep(
    sample: LocusSample, ra: float | None, dec: float | None
) -> tuple[float, float]:
    if ra is not None and dec is not None and math.isfinite(ra) and math.isfinite(dec):
        return ra, dec
    return sample.icrs_ra_deg, sample.icrs_dec_deg


def _zone_for(
    samples: tuple[LocusSample, ...],
    assumed_half_width_arcsec: float | None,
    exposure_s: float | None,
) -> _Zone:
    # The corridor is ordered by ascending z, so the group's true sky
    # extremes are the first sample's near boundary and the last sample's
    # far boundary; center on those, and require the footprint to contain
    # every represented interval boundary, not just representative points.
    first, last = samples[0], samples[-1]
    near_end = _boundary_or_rep(first, first.near_icrs_ra_deg, first.near_icrs_dec_deg)
    far_end = _boundary_or_rep(last, last.far_icrs_ra_deg, last.far_icrs_dec_deg)
    v_first = _unit(*near_end)
    v_last = _unit(*far_end)
    center = _radec(
        (
            v_first[0] + v_last[0],
            v_first[1] + v_last[1],
            v_first[2] + v_last[2],
        )
    )
    extent = max(
        _separation_arcsec(center[0], center[1], ra, dec)
        for s in samples
        for ra, dec in s.coverage_radec()
    )
    padding = 0.0
    if exposure_s is not None:
        fastest = max(
            math.hypot(
                s.rate_ra_cosdec_arcsec_per_hr or 0.0, s.rate_dec_arcsec_per_hr or 0.0
            )
            for s in samples
        )
        fastest = max(
            fastest,
            max(
                math.hypot(
                    s.near_rate_ra_cosdec_arcsec_per_hr or 0.0,
                    s.near_rate_dec_arcsec_per_hr or 0.0,
                )
                for s in samples
            ),
        )
        padding = fastest * (exposure_s / 3600.0) / 2.0
    radius = extent + (assumed_half_width_arcsec or 0.0) + padding
    return _Zone(
        center_ra_deg=center[0],
        center_dec_deg=center[1],
        track_extent_arcsec=extent,
        motion_padding_arcsec=padding,
        radius_arcsec=radius,
    )


def _operational_samples(corridor: Corridor) -> tuple[LocusSample, ...]:
    """Samples eligible for observing products; validity is the gate."""
    return tuple(s for s in corridor.samples if s.is_operational)


def group_corridor_samples(
    samples: tuple[LocusSample, ...],
    *,
    usable_radius_arcsec: float,
    assumed_half_width_arcsec: float | None,
    exposure_s: float | None,
) -> tuple[tuple[tuple[LocusSample, ...], _Zone], ...]:
    """Greedy adjacent grouping of an ordered corridor into fitting zones."""
    groups: list[tuple[tuple[LocusSample, ...], _Zone]] = []
    index = 0
    while index < len(samples):
        end = index + 1
        zone = _zone_for(samples[index:end], assumed_half_width_arcsec, exposure_s)
        while end < len(samples):
            candidate = _zone_for(
                samples[index : end + 1], assumed_half_width_arcsec, exposure_s
            )
            if candidate.radius_arcsec > usable_radius_arcsec:
                break
            zone = candidate
            end += 1
        groups.append((samples[index:end], zone))
        index = end
    return tuple(groups)


def plan_commensal(
    result: CalculationResult,
    registry: TargetRegistry,
    *,
    ephemeris: Ephemeris | None = None,
) -> CalculationResult:
    """Attach visibility and candidate pointings to a generated result.

    Requires a site observer plus ``observability`` and ``fov`` blocks on the
    request. Returns a new result; the input is untouched.
    """
    request = result.request
    if request.observer.kind is not ObserverKind.SITE:
        raise PlanningError("commensal planning requires a terrestrial site observer")
    if request.observability is None:
        raise PlanningError("commensal planning requires request observability settings")
    if request.fov is None:
        raise PlanningError("commensal planning requires a request fov block")
    if ephemeris is None:
        ephemeris = AstropyEphemeris(request.ephemeris)
    iers = IersResource(request.iers) if request.iers is not None else None

    epochs = materialize_epochs(request.time)
    corridor_index: dict[tuple[str, str, str], Corridor] = {
        (c.target_id, c.role.value, c.epoch_id): c for c in result.corridors
    }

    visibility: list[VisibilitySample] = []
    planning_warnings: list[str] = []
    ordered_pointings: list[tuple[tuple[float, int, int, int, int], Pointing]] = []

    for target_index, target_id in enumerate(request.target_ids):
        priority = registry[target_id].priority
        for role_index, role in enumerate(request.roles):
            role_visibility: list[VisibilitySample] = []
            for epoch in epochs:
                corridor = corridor_index[(target_id, role.value, epoch.epoch_id)]
                operational = _operational_samples(corridor)
                # With no operational sample, the corridor middle stands in and
                # visibility_sample fails it as sample_invalid — no window forms.
                representative = (
                    operational[len(operational) // 2]
                    if operational
                    else corridor.samples[len(corridor.samples) // 2]
                )
                role_visibility.append(
                    visibility_sample(
                        sample=representative,
                        epoch=epoch,
                        observer=request.observer,
                        ephemeris=ephemeris,
                        constraints=request.observability,
                        iers=iers,
                        probe_points=_corridor_extremes(operational),
                    )
                )
            visibility.extend(role_visibility)
            windows = find_windows(
                target_id=target_id,
                role=role,
                epochs=epochs,
                visibility=tuple(role_visibility),
            )
            if not windows:
                planning_warnings.append(
                    f"{WARN_NO_VISIBLE_WINDOW}:{target_id}/{role.value}"
                )
                continue
            for window_index, window in enumerate(windows):
                corridor = corridor_index[
                    (target_id, role.value, window.representative_epoch_id)
                ]
                operational = _operational_samples(corridor)
                if not operational:
                    planning_warnings.append(
                        f"{WARN_NO_OPERATIONAL_SAMPLES}:{target_id}/{role.value}"
                    )
                    continue
                groups = group_corridor_samples(
                    operational,
                    usable_radius_arcsec=request.fov.radius_arcsec,
                    assumed_half_width_arcsec=request.assumed_half_width_arcsec,
                    exposure_s=request.fov.exposure_s,
                )
                for group_index, (group, zone) in enumerate(groups):
                    pointing = _build_pointing(
                        result=result,
                        target_id=target_id,
                        window=window,
                        group=group,
                        zone=zone,
                        usable_radius_arcsec=request.fov.radius_arcsec,
                        assumed_half_width_arcsec=request.assumed_half_width_arcsec,
                        window_drift_arcsec=_window_drift_arcsec(
                            corridor_index=corridor_index,
                            target_id=target_id,
                            role=role,
                            window=window,
                            group=group,
                            zone=zone,
                        ),
                    )
                    ordered_pointings.append(
                        (
                            (-priority, target_index, role_index, window_index, group_index),
                            pointing,
                        )
                    )

    ordered_pointings.sort(key=lambda item: item[0])
    return dataclasses.replace(
        result,
        visibility=tuple(visibility),
        pointings=tuple(pointing for _, pointing in ordered_pointings),
        warnings=(*result.warnings, *planning_warnings),
    )


def _corridor_extremes(
    operational: tuple[LocusSample, ...],
) -> tuple[tuple[float, float], ...]:
    """The corridor's angular extreme points, for worst-case visibility.

    The first operational sample's near boundary and the last one's far
    boundary bound the corridor arc (the model direction is monotonic in z
    along it), so evaluating constraints there catches an endpoint failing
    a threshold the middle sample meets.
    """
    if not operational:
        return ()
    first, last = operational[0], operational[-1]
    return (
        _boundary_or_rep(first, first.near_icrs_ra_deg, first.near_icrs_dec_deg),
        _boundary_or_rep(last, last.far_icrs_ra_deg, last.far_icrs_dec_deg),
    )


def _window_drift_arcsec(
    *,
    corridor_index: dict[tuple[str, str, str], Corridor],
    target_id: str,
    role: Role,
    window: VisibilityWindow,
    group: tuple[LocusSample, ...],
    zone: _Zone,
) -> float:
    """Extra extent the group sweeps across the window's grid epochs.

    The pointing is constructed at the window's representative epoch, but
    it advertises the whole window; the same relay segments at every other
    window epoch (already generated) bound the positional drift, so the
    radius covers the window, not just one instant. Grid-sampled like the
    window itself.
    """
    group_ids = {sample.sample_id for sample in group}
    max_extent = zone.track_extent_arcsec
    for epoch_id in window.epoch_ids:
        corridor = corridor_index.get((target_id, role.value, epoch_id))
        if corridor is None:
            continue
        for sample in corridor.samples:
            if sample.sample_id not in group_ids or not sample.is_operational:
                continue
            for ra, dec in sample.coverage_radec():
                max_extent = max(
                    max_extent,
                    _separation_arcsec(
                        zone.center_ra_deg, zone.center_dec_deg, ra, dec
                    ),
                )
    return max_extent - zone.track_extent_arcsec


#: Sample condition codes surfaced on any pointing built from them, so a
#: product consumer sees them without joining back to the samples table.
_PROPAGATED_SAMPLE_CONDITIONS = (WARN_BELOW_FOCAL, WARN_OUTSIDE_SEARCH_PRIOR)


def _build_pointing(
    *,
    result: CalculationResult,
    target_id: str,
    window: VisibilityWindow,
    group: tuple[LocusSample, ...],
    zone: _Zone,
    usable_radius_arcsec: float,
    assumed_half_width_arcsec: float | None,
    window_drift_arcsec: float,
) -> Pointing:
    radius_arcsec = zone.radius_arcsec + window_drift_arcsec
    warning_list: list[str] = []
    if radius_arcsec > usable_radius_arcsec:
        warning_list.append(WARN_GROUP_EXCEEDS_FOV)
    group_codes = {code for sample in group for code in sample.warnings}
    warning_list.extend(
        code for code in _PROPAGATED_SAMPLE_CONDITIONS if code in group_codes
    )
    warnings = tuple(warning_list)
    sample_ids = tuple(sample.sample_id for sample in group)
    pointing_id = stable_id(
        "pnt",
        {
            "calculation_id": result.calculation_id,
            "target_id": target_id,
            "role": window.role,
            "representative_epoch_id": window.representative_epoch_id,
            "sample_ids": list(sample_ids),
            "usable_radius_arcsec": usable_radius_arcsec,
            "assumed_half_width_arcsec": assumed_half_width_arcsec,
        },
    )
    return Pointing(
        pointing_id=pointing_id,
        calculation_id=result.calculation_id,
        target_id=target_id,
        role=window.role,
        sample_ids=sample_ids,
        center_icrs_ra_deg=zone.center_ra_deg,
        center_icrs_dec_deg=zone.center_dec_deg,
        radius_arcsec=radius_arcsec,
        usable_radius_arcsec=usable_radius_arcsec,
        representative_time_utc=window.representative_utc,
        window_start_utc=window.start_utc,
        window_stop_utc=window.stop_utc,
        warnings=warnings,
        track_extent_arcsec=zone.track_extent_arcsec,
        assumed_half_width_arcsec=assumed_half_width_arcsec,
        motion_padding_arcsec=zone.motion_padding_arcsec,
        z_near_au=group[0].z_near_au,
        z_far_au=group[-1].z_far_au,
        window_drift_arcsec=window_drift_arcsec,
    )
