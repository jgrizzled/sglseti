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

where ``track_extent`` is the maximal angular distance from the zone center
(spherical midpoint of the group's endpoints) to any grouped sample,
``assumed_half_width`` is the request's explicitly assumed corridor
half-width (never covariance), and ``motion_padding`` is half an exposure of
the fastest grouped sample's angular rate (only when ``fov.exposure_s`` is
configured). A group that exceeds the usable radius even as a single
segment is still emitted, flagged ``group_exceeds_usable_fov`` — pointings
are candidate zones, and hiding the segment would misstate coverage of the
hypothesis space.

Visibility for a corridor is evaluated at its middle segment's line of
sight (documented convention; corridor angular extent is small against the
constraint scales).
"""

from __future__ import annotations

import dataclasses
import math

from .ephemeris import AstropyEphemeris, Ephemeris
from .errors import PlanningError
from .generate import materialize_epochs
from .models import (
    CalculationResult,
    Corridor,
    LocusSample,
    ObserverKind,
    Pointing,
    VisibilitySample,
)
from .observability import VisibilityWindow, find_windows, visibility_sample
from .provenance import stable_id
from .targets import TargetRegistry

__all__ = [
    "WARN_GROUP_EXCEEDS_FOV",
    "WARN_NO_VISIBLE_WINDOW",
    "group_corridor_samples",
    "plan_commensal",
]

WARN_GROUP_EXCEEDS_FOV = "group_exceeds_usable_fov"
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


def _zone_for(
    samples: tuple[LocusSample, ...],
    assumed_half_width_arcsec: float | None,
    exposure_s: float | None,
) -> _Zone:
    first, last = samples[0], samples[-1]
    v_first = _unit(first.icrs_ra_deg, first.icrs_dec_deg)
    v_last = _unit(last.icrs_ra_deg, last.icrs_dec_deg)
    center = _radec(
        (
            v_first[0] + v_last[0],
            v_first[1] + v_last[1],
            v_first[2] + v_last[2],
        )
    )
    extent = max(
        _separation_arcsec(center[0], center[1], s.icrs_ra_deg, s.icrs_dec_deg)
        for s in samples
    )
    padding = 0.0
    if exposure_s is not None:
        fastest = max(
            math.hypot(
                s.rate_ra_cosdec_arcsec_per_hr or 0.0, s.rate_dec_arcsec_per_hr or 0.0
            )
            for s in samples
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
                representative = corridor.samples[len(corridor.samples) // 2]
                role_visibility.append(
                    visibility_sample(
                        sample=representative,
                        epoch=epoch,
                        observer=request.observer,
                        ephemeris=ephemeris,
                        constraints=request.observability,
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
                groups = group_corridor_samples(
                    corridor.samples,
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


def _build_pointing(
    *,
    result: CalculationResult,
    target_id: str,
    window: VisibilityWindow,
    group: tuple[LocusSample, ...],
    zone: _Zone,
    usable_radius_arcsec: float,
    assumed_half_width_arcsec: float | None,
) -> Pointing:
    warnings: tuple[str, ...] = ()
    if zone.radius_arcsec > usable_radius_arcsec:
        warnings = (WARN_GROUP_EXCEEDS_FOV,)
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
        radius_arcsec=zone.radius_arcsec,
        usable_radius_arcsec=usable_radius_arcsec,
        representative_time_utc=window.representative_utc,
        window_start_utc=window.start_utc,
        window_stop_utc=window.stop_utc,
        warnings=warnings,
        track_extent_arcsec=zone.track_extent_arcsec,
        assumed_half_width_arcsec=assumed_half_width_arcsec,
        motion_padding_arcsec=zone.motion_padding_arcsec,
    )
