"""Beam-crossing search: the ``sun_star_axis_v1`` impact-parameter model.

Implements the crossing axis contract (ADR-0003): the hypothesized beam of a
target's relay link is a line anchored at the Sun's barycentric position
along the role-propagated catalog direction, and a "crossing" is a local
minimum of the observer's perpendicular distance to that axis,

    b(t) = | r(t) - (r(t) . a(u_role)) a(u_role) |,   r = observer - Sun,

reported as the impact parameter itself — never a binary verdict, because
detectability depends on beam physics this package does not model. The link
direction selects the frozen ``tusay2022_eq5_7_v1`` catalog epoch of the
axis:

- ``inbound`` (star -> relay uplink): light passing the observer at ``t_o``
  is arriving now, so the axis is the apparent state ``u = t_o``
  (``antipode`` role);
- ``outbound`` (relay -> star downlink): the relay's aim direction
  ``u = t_o + 2d/c`` (``tx`` role). The relay-emission retardation of the
  epoch (``~z/c``) is neglected, a declared approximation of the same class
  as the model's ``rho = z``.

The signed along-axis distance ``r . a`` distinguishes the post-lens target
side from the anti-target side. Searching is deterministic and offline: a
coarse scan brackets minima (the impact-parameter history of a one-AU
observer has at most semiannual structure), golden-section refinement
locates each closest approach, and bisection solves assumed-beam-radius
ingress/egress boundaries. Assumed radii are caller hypotheses, labeled as
such; impact-parameter uncertainty is not propagated (warning attached).

This module computes; it never reads YAML, writes files, or queries
archives. Astropy is imported normally at module level (geometry-heavy
module, like :mod:`sglseti.geometry`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from astropy.time import Time, TimeDelta

from .ephemeris import AstropyEphemeris, Ephemeris, offline_resources
from .errors import EphemerisCoverageError, GenerationError
from .generate import (
    _MODEL_REGISTRY,
    MAX_MATERIALIZED_EPOCHS,
    WARN_EPHEMERIS_COVERAGE,
    WARN_UNCERTAINTY_NOT_PROPAGATED,
)
from .geometry import (
    C_AU_PER_DAY,
    GeometryModel,
    _radec_deg,
    _unit_vector,
    observer_barycentric_au,
)
from .models import (
    BeamSide,
    BeamWindow,
    CrossingEvent,
    CrossingsRequest,
    CrossingsResult,
    DirectionSolution,
    ImpactSample,
    LinkDirection,
    Observer,
    Role,
    Target,
    TimeInterval,
    UncertaintyMethod,
    Validity,
)
from .provenance import canonicalize, stable_hash, stable_id
from .targets import TargetRegistry

__all__ = [
    "AXIS_MODEL_ID",
    "AXIS_MODEL_VERSION",
    "KM_PER_AU",
    "SOLAR_RADIUS_KM",
    "V_PERP_STEP_S",
    "WARN_MINIMUM_AT_INTERVAL_START",
    "WARN_MINIMUM_AT_INTERVAL_STOP",
    "find_crossings",
    "impact_parameter",
]

#: The crossing axis contract identity (ADR-0003). The catalog direction it
#: consumes keeps its own model identity (``tusay2022_eq5_7_v1``); both are
#: recorded on every product row.
AXIS_MODEL_ID = "sun_star_axis_v1"
AXIS_MODEL_VERSION = "1.0.0"

#: IAU 2012 definition of the astronomical unit.
KM_PER_AU = 149_597_870.700

#: IAU 2015 nominal solar radius (unit conversion for reporting only).
SOLAR_RADIUS_KM = 695_700.0

#: Central finite-difference step for the transverse-velocity diagnostic.
V_PERP_STEP_S = 3600.0

#: A boundary minimum: the impact parameter was still decreasing toward (or
#: minimal at) the requested interval's edge, so the true closest approach
#: may lie outside the searched span. The event is degraded, never hidden.
WARN_MINIMUM_AT_INTERVAL_START = "minimum_at_interval_start"
WARN_MINIMUM_AT_INTERVAL_STOP = "minimum_at_interval_stop"

#: Link direction -> frozen catalog direction epoch of the beam axis
#: (ADR-0003): inbound light arriving at the observer now is the apparent
#: state; outbound light follows the relay's tx aim direction.
_LINK_ROLE = {
    LinkDirection.INBOUND: Role.ANTIPODE,
    LinkDirection.OUTBOUND: Role.TX,
}

_INVPHI = (math.sqrt(5.0) - 1.0) / 2.0


@dataclass(frozen=True)
class _AxisState:
    """One full evaluation of the axis metric at an instant."""

    time: Time
    direction: DirectionSolution
    axis_hat: np.ndarray
    sun_au: np.ndarray
    observer_au: np.ndarray
    perp_au: np.ndarray
    b_au: float
    s_au: float


def _axis_state(
    *,
    target: Target,
    time: Time,
    z_au: float,
    link_direction: LinkDirection,
    observer: Observer,
    ephemeris: Ephemeris,
    model: GeometryModel,
) -> _AxisState:
    with offline_resources():
        direction = model.target_direction(
            target, time, z_au, _LINK_ROLE[link_direction], ephemeris
        )
        sun = np.asarray(ephemeris.sun_barycentric_au(time), dtype=float)
        obs = observer_barycentric_au(observer, time, ephemeris)
    axis_hat = _unit_vector(
        direction.target_direction_icrs_ra_deg,
        direction.target_direction_icrs_dec_deg,
    )
    helio = obs - sun
    s_au = float(np.dot(helio, axis_hat))
    perp = helio - s_au * axis_hat
    return _AxisState(
        time=time,
        direction=direction,
        axis_hat=axis_hat,
        sun_au=sun,
        observer_au=obs,
        perp_au=perp,
        b_au=float(np.linalg.norm(perp)),
        s_au=s_au,
    )


def impact_parameter(
    *,
    target: Target,
    time: Time,
    link_direction: LinkDirection,
    observer: Observer,
    z_au: float,
    ephemeris: Ephemeris,
    model: GeometryModel | None = None,
) -> ImpactSample:
    """Evaluate the beam-axis impact parameter at one instant.

    The cheap point query for commensal consumers: an external tool holding
    a telescope's actual schedule can ask whether a pointing epoch sits near
    a hypothesized beam without running a scan. Raises
    :class:`~sglseti.errors.EphemerisCoverageError` for epochs outside the
    ephemeris coverage (no batch isolation at this level).
    """
    if model is None:
        model = _MODEL_REGISTRY["tusay2022_eq5_7_v1"]()
    state = _axis_state(
        target=target,
        time=time,
        z_au=z_au,
        link_direction=link_direction,
        observer=observer,
        ephemeris=ephemeris,
        model=model,
    )
    direction = state.direction
    return ImpactSample(
        target_id=target.target_id,
        link_direction=link_direction,
        observer_id=observer.observer_id,
        time_utc=str(time.utc.isot),
        time_tdb_jd=float(time.tdb.jd),
        b_au=state.b_au,
        b_km=state.b_au * KM_PER_AU,
        b_solar_radii=state.b_au * KM_PER_AU / SOLAR_RADIUS_KM,
        axis_distance_au=state.s_au,
        side=BeamSide.TARGET if state.s_au >= 0.0 else BeamSide.ANTI_TARGET,
        axis_icrs_ra_deg=direction.target_direction_icrs_ra_deg,
        axis_icrs_dec_deg=direction.target_direction_icrs_dec_deg,
        role=_LINK_ROLE[link_direction],
        z_au=z_au,
        axis_model_id=AXIS_MODEL_ID,
        axis_model_version=AXIS_MODEL_VERSION,
        model_id=direction.model_id,
        model_version=direction.model_version,
        validity=direction.validity,
        warnings=direction.warnings,
    )


def find_crossings(
    request: CrossingsRequest,
    registry: TargetRegistry,
    *,
    model: GeometryModel | None = None,
    ephemeris: Ephemeris | None = None,
    strict: bool = False,
) -> CrossingsResult:
    """Search every requested combination for beam crossings.

    The deterministic product order is targets (request order) x link
    directions (request order) x intervals (request order) x minima
    (ascending time). An ephemeris-coverage failure yields one ``invalid``
    status row for that combination only (NaN geometry, machine-readable
    reason) so the searched coverage is never silently misstated;
    ``strict=True`` instead fails the whole batch. ``model`` and
    ``ephemeris`` default to what the request specifies and exist for
    testing with deterministic fakes.
    """
    unknown = [tid for tid in request.target_ids if tid not in registry]
    if unknown:
        raise GenerationError(
            f"unknown target ID(s) {unknown}; registry contains {sorted(registry.ids)}"
        )
    if model is None:
        model = _MODEL_REGISTRY[request.model_id]()
    if ephemeris is None:
        ephemeris = AstropyEphemeris(request.ephemeris)

    targets = [registry[tid] for tid in request.target_ids]
    target_hashes = {target.target_id: stable_hash(target) for target in targets}
    crossings_id = _crossings_id(request, model, ephemeris, target_hashes)

    events: list[CrossingEvent] = []
    invalid_count = 0
    degraded_count = 0
    for target in targets:
        for link_direction in request.link_directions:
            for interval in request.intervals:
                try:
                    combination_events = _scan_combination(
                        request=request,
                        target=target,
                        link_direction=link_direction,
                        interval=interval,
                        model=model,
                        ephemeris=ephemeris,
                        crossings_id=crossings_id,
                        target_source_hash=target_hashes[target.target_id],
                    )
                except EphemerisCoverageError as exc:
                    if strict:
                        raise GenerationError(
                            "strict mode: ephemeris coverage failure for "
                            f"target={target.target_id} "
                            f"link_direction={link_direction} "
                            f"interval={interval.interval_id}: {exc}"
                        ) from exc
                    combination_events = [
                        _invalid_event(
                            request=request,
                            target=target,
                            link_direction=link_direction,
                            interval=interval,
                            model=model,
                            ephemeris_id=ephemeris.ephemeris_id,
                            crossings_id=crossings_id,
                            target_source_hash=target_hashes[target.target_id],
                            reason=f"{WARN_EPHEMERIS_COVERAGE}: {exc}",
                        )
                    ]
                for event in combination_events:
                    if event.validity is Validity.INVALID:
                        invalid_count += 1
                    elif event.validity is Validity.DEGRADED:
                        degraded_count += 1
                events.extend(combination_events)

    warnings: list[str] = [WARN_UNCERTAINTY_NOT_PROPAGATED]
    if invalid_count:
        warnings.append(f"invalid_event_count:{invalid_count}")
    if degraded_count:
        warnings.append(f"degraded_event_count:{degraded_count}")
    return CrossingsResult(
        crossings_id=crossings_id,
        request=request,
        events=tuple(events),
        warnings=tuple(warnings),
    )


def _crossings_id(
    request: CrossingsRequest,
    model: GeometryModel,
    ephemeris: Ephemeris,
    target_hashes: dict[str, str],
) -> str:
    canonical_request = canonicalize(request)
    # Content identity, never location (matches _calculation_id).
    canonical_request["fields"]["ephemeris"] = ephemeris.ephemeris_id
    return stable_id(
        "xng",
        {
            "request": canonical_request,
            "axis_model": {"id": AXIS_MODEL_ID, "version": AXIS_MODEL_VERSION},
            "model": {"id": model.model_id, "version": model.model_version},
            "target_source_hashes": dict(sorted(target_hashes.items())),
            "ephemeris_id": ephemeris.ephemeris_id,
        },
    )


def _event_id(
    crossings_id: str,
    target_id: str,
    link_direction: LinkDirection,
    interval_id: str,
    minimum_index: int,
) -> str:
    return stable_id(
        "evt",
        {
            "crossings_id": crossings_id,
            "target_id": target_id,
            "link_direction": link_direction,
            "interval_id": interval_id,
            "minimum_index": minimum_index,
        },
    )


def _scan_combination(
    *,
    request: CrossingsRequest,
    target: Target,
    link_direction: LinkDirection,
    interval: TimeInterval,
    model: GeometryModel,
    ephemeris: Ephemeris,
    crossings_id: str,
    target_source_hash: str,
) -> list[CrossingEvent]:
    start = interval.start.tdb
    span_days = float((interval.stop.tdb - start).jd)
    step = request.coarse_step_days
    count = math.floor(span_days / step) + 1
    if count + 1 > MAX_MATERIALIZED_EPOCHS:
        raise GenerationError(
            f"interval {interval.interval_id!r} would need {count + 1} coarse "
            f"evaluations at {step:g} d cadence; limit is {MAX_MATERIALIZED_EPOCHS}"
        )
    offsets = [k * step for k in range(count)]
    if span_days - offsets[-1] > 1e-9:
        offsets.append(span_days)
    else:
        offsets[-1] = span_days

    def state_at(offset_days: float) -> _AxisState:
        time = start + TimeDelta(offset_days, format="jd", scale="tdb")
        return _axis_state(
            target=target,
            time=time,
            z_au=request.relay_distance_au,
            link_direction=link_direction,
            observer=request.observer,
            ephemeris=ephemeris,
            model=model,
        )

    def b_at(offset_days: float) -> float:
        return state_at(offset_days).b_au

    b = [b_at(offset) for offset in offsets]
    tolerance_days = request.refine_tolerance_s / 86_400.0

    # Bracketed interior minima plus boundary minima. A tie with a
    # neighbor counts on the left comparison only, so a flat pair cannot
    # produce two events for one physical minimum.
    minima: list[tuple[float, str | None]] = []
    if len(b) >= 2 and b[0] < b[1]:
        minima.append((offsets[0], WARN_MINIMUM_AT_INTERVAL_START))
    for k in range(1, len(b) - 1):
        if b[k] < b[k - 1] and b[k] <= b[k + 1]:
            refined = _golden_minimize(
                b_at, offsets[k - 1], offsets[k + 1], tolerance_days
            )
            minima.append((refined, None))
    if len(b) >= 2 and b[-1] < b[-2]:
        minima.append((offsets[-1], WARN_MINIMUM_AT_INTERVAL_STOP))

    events: list[CrossingEvent] = []
    for offset, truncation in minima:
        state = state_at(offset)
        if (
            request.report_max_b_au is not None
            and state.b_au > request.report_max_b_au
        ):
            continue
        events.append(
            _build_event(
                request=request,
                target=target,
                link_direction=link_direction,
                interval=interval,
                state=state,
                offset_days=offset,
                span_days=span_days,
                truncation=truncation,
                state_at=state_at,
                b_at=b_at,
                crossings_id=crossings_id,
                target_source_hash=target_source_hash,
                ephemeris_id=ephemeris.ephemeris_id,
                minimum_index=len(events),
            )
        )
    return events


def _build_event(
    *,
    request: CrossingsRequest,
    target: Target,
    link_direction: LinkDirection,
    interval: TimeInterval,
    state: _AxisState,
    offset_days: float,
    span_days: float,
    truncation: str | None,
    state_at: Callable[[float], _AxisState],
    b_at: Callable[[float], float],
    crossings_id: str,
    target_source_hash: str,
    ephemeris_id: str,
    minimum_index: int,
) -> CrossingEvent:
    direction = state.direction

    # Transverse velocity of the observer relative to the axis: the rate of
    # the perpendicular displacement vector (includes axis drift), central
    # finite difference clamped to the interval.
    half_days = V_PERP_STEP_S / 86_400.0 / 2.0
    lo = max(0.0, offset_days - half_days)
    hi = min(span_days, offset_days + half_days)
    perp_lo = state_at(lo).perp_au
    perp_hi = state_at(hi).perp_au
    v_perp_au_per_day = float(np.linalg.norm(perp_hi - perp_lo)) / (hi - lo)
    v_perp_km_s = v_perp_au_per_day * KM_PER_AU / 86_400.0

    # Observer-relative geometric pointings at closest approach: the
    # propagated star (with its parallax from the observer offset) and the
    # hypothesized relay at the representative distance.
    d_au = direction.target_light_time_days * C_AU_PER_DAY
    star_ra, star_dec = _radec_deg(d_au * state.axis_hat - state.observer_au)
    relay = state.sun_au - request.relay_distance_au * state.axis_hat
    relay_ra, relay_dec = _radec_deg(relay - state.observer_au)

    event_id = _event_id(
        crossings_id,
        target.target_id,
        link_direction,
        interval.interval_id,
        minimum_index,
    )
    windows = _beam_windows(
        request=request,
        event_id=event_id,
        b_min_au=state.b_au,
        offset_days=offset_days,
        span_days=span_days,
        b_at=b_at,
        start=interval.start.tdb,
    )

    warnings = list(direction.warnings)
    validity = direction.validity
    if truncation is not None:
        # The true closest approach may lie outside the searched interval:
        # degraded, never hidden and never presented as a clean minimum.
        warnings.append(truncation)
        validity = Validity.DEGRADED if validity is Validity.VALID else validity

    return CrossingEvent(
        crossings_id=crossings_id,
        event_id=event_id,
        target_id=target.target_id,
        link_direction=link_direction,
        interval_id=interval.interval_id,
        minimum_index=minimum_index,
        observer_id=request.observer.observer_id,
        t_ca_utc=str(state.time.utc.isot),
        t_ca_tdb_jd=float(state.time.tdb.jd),
        catalog_direction_epoch_tdb_jd=float(direction.catalog_direction_epoch.jd),
        b_min_au=state.b_au,
        b_min_km=state.b_au * KM_PER_AU,
        b_min_solar_radii=state.b_au * KM_PER_AU / SOLAR_RADIUS_KM,
        axis_distance_au=state.s_au,
        v_perp_km_s=v_perp_km_s,
        axis_icrs_ra_deg=direction.target_direction_icrs_ra_deg,
        axis_icrs_dec_deg=direction.target_direction_icrs_dec_deg,
        star_icrs_ra_deg=star_ra,
        star_icrs_dec_deg=star_dec,
        relay_icrs_ra_deg=relay_ra,
        relay_icrs_dec_deg=relay_dec,
        z_au=request.relay_distance_au,
        target_light_time_days=direction.target_light_time_days,
        role=_LINK_ROLE[link_direction],
        axis_model_id=AXIS_MODEL_ID,
        axis_model_version=AXIS_MODEL_VERSION,
        model_id=direction.model_id,
        model_version=direction.model_version,
        target_source_hash=target_source_hash,
        ephemeris_id=ephemeris_id,
        validity=validity,
        uncertainty_method=UncertaintyMethod.NOT_PROPAGATED,
        side=BeamSide.TARGET if state.s_au >= 0.0 else BeamSide.ANTI_TARGET,
        warnings=tuple(warnings),
        windows=windows,
    )


def _beam_windows(
    *,
    request: CrossingsRequest,
    event_id: str,
    b_min_au: float,
    offset_days: float,
    span_days: float,
    b_at: Callable[[float], float],
    start: Time,
) -> tuple[BeamWindow, ...]:
    windows: list[BeamWindow] = []
    step = request.coarse_step_days
    tolerance_days = request.refine_tolerance_s / 86_400.0
    for radius in request.beam_radii_au:
        if b_min_au > radius:
            continue
        ingress, truncated_ingress = _boundary_crossing(
            b_at, radius, offset_days, 0.0, -step, tolerance_days
        )
        egress, truncated_egress = _boundary_crossing(
            b_at, radius, offset_days, span_days, step, tolerance_days
        )
        ingress_time = start + TimeDelta(ingress, format="jd", scale="tdb")
        egress_time = start + TimeDelta(egress, format="jd", scale="tdb")
        windows.append(
            BeamWindow(
                window_id=stable_id(
                    "win", {"event_id": event_id, "beam_radius_au": radius}
                ),
                event_id=event_id,
                beam_radius_au=radius,
                ingress_utc=str(ingress_time.utc.isot),
                egress_utc=str(egress_time.utc.isot),
                ingress_tdb_jd=float(ingress_time.tdb.jd),
                egress_tdb_jd=float(egress_time.tdb.jd),
                duration_days=egress - ingress,
                truncated_ingress=truncated_ingress,
                truncated_egress=truncated_egress,
            )
        )
    return tuple(windows)


def _boundary_crossing(
    b_at: Callable[[float], float],
    radius: float,
    inside_offset: float,
    limit_offset: float,
    step: float,
    tolerance_days: float,
) -> tuple[float, bool]:
    """Walk from an inside-the-beam offset toward ``limit_offset`` until the
    impact parameter exceeds ``radius``, then bisect the boundary.

    Returns ``(offset_days, truncated)``; truncated means the impact
    parameter was still inside the radius at the interval limit.
    """
    assert callable(b_at)
    previous = inside_offset
    while True:
        toward_limit = previous + step
        reached_limit = (step > 0 and toward_limit >= limit_offset) or (
            step < 0 and toward_limit <= limit_offset
        )
        probe = limit_offset if reached_limit else toward_limit
        if b_at(probe) > radius:
            break
        if reached_limit:
            return limit_offset, True
        previous = probe
    lo, hi = (previous, probe) if step > 0 else (probe, previous)
    # Invariant: exactly one of (lo, hi) is inside the beam; bisect on that.
    inside_is_lo = step > 0
    while hi - lo > tolerance_days:
        mid = (lo + hi) / 2.0
        if (b_at(mid) <= radius) == inside_is_lo:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0, False


def _golden_minimize(
    fn: Callable[[float], float], lo: float, hi: float, tolerance_days: float
) -> float:
    """Golden-section minimum of a unimodal scalar function of days."""
    a, b = lo, hi
    c = b - _INVPHI * (b - a)
    d = a + _INVPHI * (b - a)
    fc, fd = fn(c), fn(d)
    while (b - a) > tolerance_days:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _INVPHI * (b - a)
            fc = fn(c)
        else:
            a, c, fc = c, d, fd
            d = a + _INVPHI * (b - a)
            fd = fn(d)
    return (a + b) / 2.0


def _invalid_event(
    *,
    request: CrossingsRequest,
    target: Target,
    link_direction: LinkDirection,
    interval: TimeInterval,
    model: GeometryModel,
    ephemeris_id: str,
    crossings_id: str,
    target_source_hash: str,
    reason: str,
) -> CrossingEvent:
    """An explicitly invalid status row: NaN geometry, never fake values.

    Emitted once per failed combination so the searched coverage is never
    silently misstated; ``t_ca`` reports the interval start as the label of
    the unsearched span.
    """
    nan = float("nan")
    return CrossingEvent(
        crossings_id=crossings_id,
        event_id=_event_id(
            crossings_id,
            target.target_id,
            link_direction,
            interval.interval_id,
            0,
        ),
        target_id=target.target_id,
        link_direction=link_direction,
        interval_id=interval.interval_id,
        minimum_index=0,
        observer_id=request.observer.observer_id,
        t_ca_utc=str(interval.start.utc.isot),
        t_ca_tdb_jd=nan,
        catalog_direction_epoch_tdb_jd=nan,
        b_min_au=nan,
        b_min_km=nan,
        b_min_solar_radii=nan,
        axis_distance_au=nan,
        v_perp_km_s=nan,
        axis_icrs_ra_deg=nan,
        axis_icrs_dec_deg=nan,
        star_icrs_ra_deg=nan,
        star_icrs_dec_deg=nan,
        relay_icrs_ra_deg=nan,
        relay_icrs_dec_deg=nan,
        z_au=request.relay_distance_au,
        target_light_time_days=nan,
        role=_LINK_ROLE[link_direction],
        axis_model_id=AXIS_MODEL_ID,
        axis_model_version=AXIS_MODEL_VERSION,
        model_id=model.model_id,
        model_version=model.model_version,
        target_source_hash=target_source_hash,
        ephemeris_id=ephemeris_id,
        validity=Validity.INVALID,
        uncertainty_method=UncertaintyMethod.NOT_PROPAGATED,
        warnings=(reason,),
    )
