"""Continuous and adaptive locus evaluation (roadmap §3.1-§3.2).

Public evaluators for the continuous mapping

    (target, role, observation time, observer, z) -> geometric ICRS direction

plus samplers that turn it into consumer-facing products:

- :func:`evaluate_locus` — one point of the continuous mapping;
- :func:`adaptive_locus` — an ordered polyline over a relay range whose
  angular deviation from the continuous locus is bounded by a
  caller-selected tolerance (tied to an instrument's pixel scale or PSF
  rather than an arbitrary sample count);
- :func:`swept_locus` — a conservative swept envelope over a first-class
  :class:`~sglseti.models.ObservationInterval`;
- :func:`covered_z_intervals` — refine a caller-supplied geometric
  containment test into covered relay-distance intervals; and
- :func:`interval_states` — target position and motion rates at an
  interval's representative times.

Guarantee mechanics: sampling works in reciprocal distance ``q = 1/z``,
where the locus is nearly linear. A segment is accepted only when the
deviation measured at its 1/4, 1/2, and 3/4 probe points is at most HALF
the tolerance; the factor-two margin covers the smooth non-parabolic
remainder, so the returned polyline is within the full tolerance of the
continuous locus for this model family's smooth loci. When an evaluation
budget stops refinement first, the product carries an explicit warning —
the bound is never silently weakened. The time sweep applies the same
midpoint-probe scheme to whole polylines and assumes smooth drift between
adjacent sampled times (Earth-motion dominated for supported observers).

Footprint knowledge stays downstream: :func:`covered_z_intervals` takes an
opaque ``contains(ra_deg, dec_deg)`` predicate, never an archive footprint
schema. Exact detector polygons, WCS distortion, chip gaps, and masks
belong to the survey consumer (roadmap §5).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from astropy.time import Time

from .ephemeris import Ephemeris
from .geometry import GeometryModel, compute_relay_solution, motion_rates
from .models import (
    AdaptiveLocus,
    IntervalState,
    LocusPoint,
    ObservationInterval,
    Observer,
    RelayRange,
    Role,
    SweptLocus,
    Target,
    ZInterval,
)

__all__ = [
    "WARN_ADAPTIVE_BUDGET",
    "WARN_TIME_BUDGET",
    "adaptive_locus",
    "covered_z_intervals",
    "evaluate_locus",
    "interval_states",
    "swept_locus",
]

#: The z-refinement budget stopped subdivision before every probe met the
#: half-tolerance acceptance bound; the polyline's guarantee is weakened.
WARN_ADAPTIVE_BUDGET = "adaptive_budget_exhausted"

#: The time-refinement budget stopped subdivision before adjacent-time
#: polylines met the half-tolerance acceptance bound.
WARN_TIME_BUDGET = "time_sampling_budget_exhausted"

#: Probe fractions (in q) at which a candidate segment is tested.
_PROBE_FRACTIONS = (0.25, 0.5, 0.75)
_MAX_DEPTH = 40


# ---------------------------------------------------------------------------
# Spherical helpers
# ---------------------------------------------------------------------------


def _unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    vector: np.ndarray = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    return vector


def _point_vec(point: LocusPoint) -> np.ndarray:
    return _unit(point.icrs_ra_deg, point.icrs_dec_deg)


def _angle_arcsec(a: np.ndarray, b: np.ndarray) -> float:
    cross = float(np.linalg.norm(np.cross(a, b)))
    dot = float(np.dot(a, b))
    return math.degrees(math.atan2(cross, dot)) * 3600.0


def _point_segment_arcsec(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Angular distance from ``p`` to the great-circle segment ``a``-``b``."""
    normal = np.cross(a, b)
    normal_norm = float(np.linalg.norm(normal))
    if normal_norm < 1e-15:
        return _angle_arcsec(p, a)
    normal_hat = normal / normal_norm
    projected = p - float(np.dot(p, normal_hat)) * normal_hat
    projected_norm = float(np.linalg.norm(projected))
    if projected_norm < 1e-15:
        return min(_angle_arcsec(p, a), _angle_arcsec(p, b))
    foot = projected / projected_norm
    inside = (
        float(np.dot(np.cross(a, foot), normal_hat)) >= 0.0
        and float(np.dot(np.cross(foot, b), normal_hat)) >= 0.0
    )
    if inside:
        sine = min(1.0, max(-1.0, float(np.dot(p, normal_hat))))
        return abs(math.degrees(math.asin(sine))) * 3600.0
    return min(_angle_arcsec(p, a), _angle_arcsec(p, b))


def _point_polyline_arcsec(p: np.ndarray, vectors: list[np.ndarray]) -> float:
    if len(vectors) == 1:
        return _angle_arcsec(p, vectors[0])
    return min(
        _point_segment_arcsec(p, vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)
    )


# ---------------------------------------------------------------------------
# Continuous evaluation
# ---------------------------------------------------------------------------


def evaluate_locus(
    *,
    target: Target,
    role: Role,
    observation_time: Time,
    observer: Observer,
    z_au: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
) -> LocusPoint:
    """One point of the continuous locus mapping (roadmap §3.2).

    Geometric ICRS direction of the hypothesized relay at heliocentric
    distance ``z_au`` for the given target, role, time, and observer, with
    the direction solution's validity and warnings carried verbatim.
    """
    solution = compute_relay_solution(
        target=target,
        observation_time=observation_time,
        z_au=float(z_au),
        role=role,
        observer=observer,
        ephemeris=ephemeris,
        model=model,
    )
    return LocusPoint(
        z_au=float(z_au),
        q_per_au=1.0 / float(z_au),
        icrs_ra_deg=solution.los_icrs_ra_deg,
        icrs_dec_deg=solution.los_icrs_dec_deg,
        validity=solution.direction.validity,
        warnings=solution.direction.warnings,
    )


# ---------------------------------------------------------------------------
# Adaptive sampling in relay distance
# ---------------------------------------------------------------------------


def adaptive_locus(
    *,
    target: Target,
    role: Role,
    observation_time: Time,
    observer: Observer,
    relay_range: RelayRange,
    tolerance_arcsec: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
    max_points: int = 4096,
) -> AdaptiveLocus:
    """Adaptively sampled locus polyline with a guaranteed angular bound.

    Bisects in reciprocal distance until the deviation at every accepted
    segment's probe points is at most ``tolerance_arcsec / 2``, so the
    returned polyline stays within ``tolerance_arcsec`` of the continuous
    locus. ``max_points`` bounds the polyline size; exhausting it attaches
    :data:`WARN_ADAPTIVE_BUDGET` instead of silently weakening the bound.
    """
    if not math.isfinite(tolerance_arcsec) or tolerance_arcsec <= 0.0:
        raise ValueError(f"tolerance_arcsec must be positive, got {tolerance_arcsec}")
    if max_points < 2:
        raise ValueError(f"max_points must be at least 2, got {max_points}")

    def evaluate(z_au: float) -> LocusPoint:
        return evaluate_locus(
            target=target,
            role=role,
            observation_time=observation_time,
            observer=observer,
            z_au=z_au,
            ephemeris=ephemeris,
            model=model,
        )

    first = evaluate(relay_range.z_min_au)
    last = evaluate(relay_range.z_max_au)
    knots: list[LocusPoint] = [first]
    achieved = 0.0
    budget_hit = False
    half_tolerance = 0.5 * tolerance_arcsec
    committed_points = 2  # endpoints; each split commits exactly one midpoint

    def refine(low: LocusPoint, high: LocusPoint, depth: int) -> None:
        # ``low``/``high`` bound a segment with low.z < high.z; interior
        # knots are appended in z order between them.
        nonlocal achieved, budget_hit, committed_points
        vec_low = _point_vec(low)
        vec_high = _point_vec(high)
        probes = []
        for fraction in _PROBE_FRACTIONS:
            q = low.q_per_au + fraction * (high.q_per_au - low.q_per_au)
            probes.append(evaluate(1.0 / q))
        deviation = max(
            _point_segment_arcsec(_point_vec(probe), vec_low, vec_high) for probe in probes
        )
        if deviation <= half_tolerance or depth >= _MAX_DEPTH or committed_points >= max_points:
            achieved = max(achieved, deviation)
            if deviation > half_tolerance:
                budget_hit = True
            return
        committed_points += 1
        midpoint = probes[1]
        refine(low, midpoint, depth + 1)
        knots.append(midpoint)
        refine(midpoint, high, depth + 1)

    refine(first, last, 0)
    knots.append(last)
    warnings = (WARN_ADAPTIVE_BUDGET,) if budget_hit else ()
    return AdaptiveLocus(
        target_id=target.target_id,
        role=role,
        observation_time=observation_time,
        observer_id=observer.observer_id,
        z_min_au=relay_range.z_min_au,
        z_max_au=relay_range.z_max_au,
        tolerance_arcsec=tolerance_arcsec,
        achieved_deviation_arcsec=achieved,
        points=tuple(knots),
        model_id=model.model_id,
        model_version=model.model_version,
        ephemeris_id=ephemeris.ephemeris_id,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Swept locus over an observation interval
# ---------------------------------------------------------------------------


def swept_locus(
    *,
    target: Target,
    role: Role,
    interval: ObservationInterval,
    observer: Observer,
    relay_range: RelayRange,
    tolerance_arcsec: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
    time_tolerance_arcsec: float | None = None,
    max_time_samples: int = 64,
    max_points: int = 4096,
) -> SweptLocus:
    """Conservative swept locus over an observation interval (§3.1).

    Adaptively bisects the interval in time until the polyline midway
    between adjacent sampled times deviates from its neighbors by at most
    ``time_tolerance_arcsec / 2``. Under the smooth-drift assumption, every
    instantaneous locus point in the interval then lies within
    ``envelope_pad_arcsec = time_tolerance + tolerance`` of the union of
    the returned polylines. Budget exhaustion attaches
    :data:`WARN_TIME_BUDGET` rather than silently weakening the claim.
    """
    time_tolerance = tolerance_arcsec if time_tolerance_arcsec is None else time_tolerance_arcsec
    if not math.isfinite(time_tolerance) or time_tolerance <= 0.0:
        raise ValueError(f"time_tolerance_arcsec must be positive, got {time_tolerance}")
    if max_time_samples < 2:
        raise ValueError(f"max_time_samples must be at least 2, got {max_time_samples}")

    def locus_at(time: Time) -> AdaptiveLocus:
        return adaptive_locus(
            target=target,
            role=role,
            observation_time=time,
            observer=observer,
            relay_range=relay_range,
            tolerance_arcsec=tolerance_arcsec,
            ephemeris=ephemeris,
            model=model,
            max_points=max_points,
        )

    def vectors(locus: AdaptiveLocus) -> list[np.ndarray]:
        return [_point_vec(point) for point in locus.points]

    first = locus_at(interval.start)
    last = locus_at(interval.stop)
    count = 2
    budget_hit = False
    half_tolerance = 0.5 * time_tolerance
    loci: list[AdaptiveLocus] = [first]

    def deviation(middle: AdaptiveLocus, a: AdaptiveLocus, b: AdaptiveLocus) -> float:
        vectors_a = vectors(a)
        vectors_b = vectors(b)
        return max(
            min(
                _point_polyline_arcsec(vec, vectors_a),
                _point_polyline_arcsec(vec, vectors_b),
            )
            for vec in (_point_vec(point) for point in middle.points)
        )

    def refine(
        low: AdaptiveLocus, high: AdaptiveLocus, t_low: Time, t_high: Time, depth: int
    ) -> None:
        nonlocal count, budget_hit
        if count >= max_time_samples or depth >= _MAX_DEPTH:
            budget_hit = True
            return
        t_mid = t_low + 0.5 * (t_high - t_low)
        middle = locus_at(t_mid)
        count += 1
        if deviation(middle, low, high) <= half_tolerance:
            return
        refine(low, middle, t_low, t_mid, depth + 1)
        loci.append(middle)
        refine(middle, high, t_mid, t_high, depth + 1)

    refine(first, last, interval.start, interval.stop, 0)
    loci.append(last)
    codes: set[str] = {w for locus in loci for w in locus.warnings}
    if budget_hit:
        codes.add(WARN_TIME_BUDGET)
    warnings = tuple(sorted(codes))
    return SweptLocus(
        interval_id=interval.interval_id,
        target_id=target.target_id,
        role=role,
        observer_id=observer.observer_id,
        loci=tuple(loci),
        tolerance_arcsec=tolerance_arcsec,
        time_tolerance_arcsec=time_tolerance,
        envelope_pad_arcsec=time_tolerance + tolerance_arcsec,
        model_id=model.model_id,
        model_version=model.model_version,
        ephemeris_id=ephemeris.ephemeris_id,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Covered relay-distance refinement
# ---------------------------------------------------------------------------


def covered_z_intervals(
    *,
    target: Target,
    role: Role,
    observation_time: Time,
    observer: Observer,
    relay_range: RelayRange,
    contains: Callable[[float, float], bool],
    tolerance_arcsec: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
    locus: AdaptiveLocus | None = None,
    seed_step_arcsec: float | None = None,
    max_points: int = 4096,
) -> tuple[ZInterval, ...]:
    """Refine a caller-supplied containment test into covered z intervals.

    ``contains(ra_deg, dec_deg)`` is the consumer's opaque geometric test
    (their footprint, WCS, and masks stay downstream). The search is seeded
    at points spaced at most ``seed_step_arcsec`` apart ALONG the locus (a
    tolerance-faithful polyline can be as coarse as two points on a
    straight locus, so deviation knots alone would miss interior covered
    stretches); each containment transition is then bisected in reciprocal
    distance until the bracketing points are within ``tolerance_arcsec`` on
    sky. Returned interval endpoints are the inside-most bracket points —
    verified covered — so the true boundary lies within the tolerance just
    outside them.

    ``seed_step_arcsec`` defaults to the refinement tolerance (robust, but
    potentially many evaluations along a long locus); pass the scale of the
    ``contains`` region (e.g. the footprint radius) to cut cost. Covered
    stretches narrower on sky than the seed step can be missed.
    """
    if locus is None:
        locus = adaptive_locus(
            target=target,
            role=role,
            observation_time=observation_time,
            observer=observer,
            relay_range=relay_range,
            tolerance_arcsec=tolerance_arcsec,
            ephemeris=ephemeris,
            model=model,
            max_points=max_points,
        )
    seed_step = tolerance_arcsec if seed_step_arcsec is None else seed_step_arcsec
    if not math.isfinite(seed_step) or seed_step <= 0.0:
        raise ValueError(f"seed_step_arcsec must be positive, got {seed_step}")

    def evaluate(z_au: float) -> LocusPoint:
        return evaluate_locus(
            target=target,
            role=role,
            observation_time=observation_time,
            observer=observer,
            z_au=z_au,
            ephemeris=ephemeris,
            model=model,
        )

    def densify(points: tuple[LocusPoint, ...]) -> list[LocusPoint]:
        """Halve knot gaps (in q) until adjacent seeds are within the step."""
        work = list(points)
        for _ in range(_MAX_DEPTH):
            out = [work[0]]
            changed = False
            for a, b in zip(work, work[1:], strict=False):
                if (
                    _angle_arcsec(_point_vec(a), _point_vec(b)) > seed_step
                    and len(work) + 1 < max_points
                ):
                    out.append(evaluate(2.0 / (a.q_per_au + b.q_per_au)))
                    changed = True
                out.append(b)
            work = out
            if not changed:
                break
        return work

    def refine_boundary(inside: LocusPoint, outside: LocusPoint) -> LocusPoint:
        for _ in range(60):
            if _angle_arcsec(_point_vec(inside), _point_vec(outside)) <= tolerance_arcsec:
                break
            q_mid = 0.5 * (inside.q_per_au + outside.q_per_au)
            middle = evaluate(1.0 / q_mid)
            if contains(middle.icrs_ra_deg, middle.icrs_dec_deg):
                inside = middle
            else:
                outside = middle
        return inside

    points = densify(locus.points)
    flags = [contains(point.icrs_ra_deg, point.icrs_dec_deg) for point in points]
    intervals: list[ZInterval] = []
    index = 0
    while index < len(points):
        if not flags[index]:
            index += 1
            continue
        run_start = index
        while index + 1 < len(points) and flags[index + 1]:
            index += 1
        run_stop = index
        if run_start == 0:
            z_low = points[0].z_au
        else:
            z_low = refine_boundary(points[run_start], points[run_start - 1]).z_au
        if run_stop == len(points) - 1:
            z_high = points[-1].z_au
        else:
            z_high = refine_boundary(points[run_stop], points[run_stop + 1]).z_au
        intervals.append(ZInterval(z_min_au=z_low, z_max_au=z_high))
        index += 1
    return tuple(intervals)


# ---------------------------------------------------------------------------
# Interval representative states
# ---------------------------------------------------------------------------


def interval_states(
    *,
    target: Target,
    role: Role,
    interval: ObservationInterval,
    observer: Observer,
    z_au: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
    rate_step_s: float = 60.0,
) -> tuple[IntervalState, ...]:
    """Target position and motion at an interval's sample times (§3.1).

    Evaluates the locus direction and central-finite-difference rates at
    ``interval.sample_times()`` — start/midpoint/stop, or the declared
    subintegration cadence grid.
    """
    states: list[IntervalState] = []
    for time in interval.sample_times():
        point = evaluate_locus(
            target=target,
            role=role,
            observation_time=time,
            observer=observer,
            z_au=z_au,
            ephemeris=ephemeris,
            model=model,
        )
        rates = motion_rates(
            target=target,
            observation_time=time,
            z_au=z_au,
            role=role,
            observer=observer,
            ephemeris=ephemeris,
            model=model,
            step_s=rate_step_s,
        )
        states.append(
            IntervalState(
                interval_id=interval.interval_id,
                time_utc=str(time.utc.isot),
                z_au=point.z_au,
                icrs_ra_deg=point.icrs_ra_deg,
                icrs_dec_deg=point.icrs_dec_deg,
                rate_ra_cosdec_arcsec_per_hr=rates.rate_ra_cosdec_arcsec_per_hr,
                rate_dec_arcsec_per_hr=rates.rate_dec_arcsec_per_hr,
                validity=point.validity,
                warnings=point.warnings,
            )
        )
    return tuple(states)
