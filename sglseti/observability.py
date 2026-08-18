"""Site observing context and simple pass/fail constraints.

Computes altitude/azimuth of a locus line of sight, Sun altitude, and Moon
separation for a terrestrial site, evaluates the request's simple
constraints, and finds every contiguous valid window on a sampled time grid
— there is no single "best time" that hides disjoint windows; each window
carries a documented representative epoch (its middle grid point).

Window boundaries are grid-sampled: constraint crossings between grid
points are not solved for, so window start/stop are accurate to the grid
cadence. Choose the request's time cadence against the constraint margins
that matter; the evaluation itself can cover a corridor's angular extremes
via ``probe_points`` so a wide corridor cannot pass on its middle sample
alone.

Conventions: directions are geometric (refraction disabled); altitudes come
from the astropy AltAz frame; Moon separation is the angle between the
topocentric Moon direction and the locus line of sight. These values assist
planning and never replace an observatory's pointing or scheduling system.

Constraint boundaries are inclusive: a value exactly at its threshold
passes.
"""

from __future__ import annotations

import math
import warnings as _warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .ephemeris import WARN_IERS_COVERAGE, Ephemeris, IersResource, offline_resources
from .errors import PlanningError
from .geometry import observer_barycentric_au
from .models import (
    Epoch,
    LocusSample,
    ObservabilityConstraints,
    Observer,
    ObserverKind,
    Role,
    VisibilitySample,
)

if TYPE_CHECKING:
    from astropy.time import Time

__all__ = [
    "VisibilityWindow",
    "evaluate_constraints",
    "find_windows",
    "visibility_sample",
]

FAIL_TARGET_ALTITUDE = "target_below_min_altitude"
FAIL_SUN_ALTITUDE = "sun_above_max_altitude"
FAIL_MOON_SEPARATION = "moon_too_close"


@dataclass(frozen=True)
class VisibilityWindow:
    """One contiguous run of grid epochs passing every constraint.

    ``representative_epoch_id`` is the window's middle grid point
    (index ``len // 2``) — a documented convention, not an optimum claim.
    """

    target_id: str
    role: Role
    epoch_ids: tuple[str, ...]
    start_utc: str
    stop_utc: str
    representative_epoch_id: str
    representative_utc: str


def evaluate_constraints(
    *,
    altitude_deg: float,
    sun_altitude_deg: float,
    moon_separation_deg: float,
    constraints: ObservabilityConstraints,
) -> tuple[bool, tuple[str, ...]]:
    """Pure inclusive-threshold evaluation, separated for direct testing."""
    failed: list[str] = []
    if altitude_deg < constraints.min_target_altitude_deg:
        failed.append(FAIL_TARGET_ALTITUDE)
    if sun_altitude_deg > constraints.max_sun_altitude_deg:
        failed.append(FAIL_SUN_ALTITUDE)
    if moon_separation_deg < constraints.min_moon_separation_deg:
        failed.append(FAIL_MOON_SEPARATION)
    return (not failed, tuple(failed))


def visibility_sample(
    *,
    sample: LocusSample,
    epoch: Epoch,
    observer: Observer,
    ephemeris: Ephemeris,
    constraints: ObservabilityConstraints,
    iers: IersResource | None = None,
    probe_points: tuple[tuple[float, float], ...] = (),
) -> VisibilitySample:
    """Evaluate site context for one locus sample at its epoch.

    ``iers`` installs a pinned Earth-orientation table for the AltAz
    transforms. Degraded Earth orientation (captured astropy warnings, or an
    epoch outside a pinned table's coverage) is recorded on the returned
    sample's ``warnings`` — never silently dropped.

    ``probe_points`` are additional geometric ICRS ``(ra, dec)`` directions
    — typically a corridor's angular extremes — whose target-altitude and
    Moon-separation constraints must also pass; the representative sample's
    values are reported, but the pass/fail verdict covers every probe so a
    corridor endpoint cannot silently fail a threshold the middle sample
    meets. Failure codes are the union across probes.
    """
    if observer.kind is not ObserverKind.SITE:
        raise PlanningError("observability requires a terrestrial site observer")
    if not sample.is_operational:
        return VisibilitySample(
            target_id=sample.target_id,
            role=sample.role,
            epoch_id=epoch.epoch_id,
            time_utc=sample.observation_time_utc,
            altitude_deg=float("nan"),
            azimuth_deg=float("nan"),
            sun_altitude_deg=float("nan"),
            moon_separation_deg=float("nan"),
            constraints_passed=False,
            failed_constraints=("sample_invalid",),
        )

    iers_table = iers.table if iers is not None else None
    warnings: list[str] = []
    if iers is not None and not iers.covers(epoch.time):
        warnings.append(WARN_IERS_COVERAGE)
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        altitude, azimuth = _direction_altaz(
            sample.icrs_ra_deg,
            sample.icrs_dec_deg,
            epoch.time,
            observer,
            iers_table=iers_table,
        )
        probe_altaz = tuple(
            _direction_altaz(ra, dec, epoch.time, observer, iers_table=iers_table)
            for ra, dec in probe_points
        )
        with offline_resources():
            observer_au = observer_barycentric_au(observer, epoch.time, ephemeris)
            sun_direction = ephemeris.sun_barycentric_au(epoch.time) - observer_au
            moon_direction = ephemeris.moon_barycentric_au(epoch.time) - observer_au
        sun_ra, sun_dec = _vector_radec(sun_direction)
        sun_altitude, _ = _direction_altaz(
            sun_ra, sun_dec, epoch.time, observer, iers_table=iers_table
        )
    warnings.extend(dict.fromkeys(f"astropy:{w.message}" for w in caught))
    moon_ra, moon_dec = _vector_radec(moon_direction)
    moon_separation = _separation_deg(
        sample.icrs_ra_deg, sample.icrs_dec_deg, moon_ra, moon_dec
    )
    passed, failed_list = evaluate_constraints(
        altitude_deg=altitude,
        sun_altitude_deg=sun_altitude,
        moon_separation_deg=moon_separation,
        constraints=constraints,
    )
    failed = list(failed_list)
    for (ra, dec), (probe_altitude, _azimuth) in zip(
        probe_points, probe_altaz, strict=True
    ):
        probe_passed, probe_failed = evaluate_constraints(
            altitude_deg=probe_altitude,
            sun_altitude_deg=sun_altitude,
            moon_separation_deg=_separation_deg(ra, dec, moon_ra, moon_dec),
            constraints=constraints,
        )
        passed = passed and probe_passed
        failed.extend(code for code in probe_failed if code not in failed)
    return VisibilitySample(
        target_id=sample.target_id,
        role=sample.role,
        epoch_id=epoch.epoch_id,
        time_utc=sample.observation_time_utc,
        altitude_deg=altitude,
        azimuth_deg=azimuth,
        sun_altitude_deg=sun_altitude,
        moon_separation_deg=moon_separation,
        constraints_passed=passed,
        failed_constraints=tuple(failed),
        warnings=tuple(warnings),
    )


def find_windows(
    *,
    target_id: str,
    role: Role,
    epochs: tuple[Epoch, ...],
    visibility: tuple[VisibilitySample, ...],
) -> tuple[VisibilityWindow, ...]:
    """Every contiguous run of passing epochs, in grid order.

    ``visibility`` must be aligned with ``epochs`` (one sample per epoch,
    same order). Disjoint windows are all returned; none is preferred.
    """
    if len(epochs) != len(visibility):
        raise PlanningError(
            f"visibility ({len(visibility)}) and epochs ({len(epochs)}) misaligned"
        )
    windows: list[VisibilityWindow] = []
    run: list[tuple[Epoch, VisibilitySample]] = []

    def close_run() -> None:
        if not run:
            return
        run_epochs = tuple(item[0] for item in run)
        representative = run_epochs[len(run_epochs) // 2]
        windows.append(
            VisibilityWindow(
                target_id=target_id,
                role=role,
                epoch_ids=tuple(epoch.epoch_id for epoch in run_epochs),
                start_utc=run[0][1].time_utc,
                stop_utc=run[-1][1].time_utc,
                representative_epoch_id=representative.epoch_id,
                representative_utc=str(representative.time.utc.isot),
            )
        )
        run.clear()

    for epoch, sample in zip(epochs, visibility, strict=True):
        if sample.constraints_passed:
            run.append((epoch, sample))
        else:
            close_run()
    close_run()
    return tuple(windows)


def _direction_altaz(
    ra_deg: float,
    dec_deg: float,
    time: Time,
    observer: Observer,
    iers_table: Any | None = None,
) -> tuple[float, float]:
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord

    assert observer.longitude_deg is not None
    location = EarthLocation.from_geodetic(
        lon=observer.longitude_deg * u.deg,
        lat=observer.latitude_deg * u.deg,
        height=observer.height_m * u.m,
    )
    with offline_resources(iers_table=iers_table):
        altaz = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs").transform_to(
            AltAz(obstime=time, location=location)
        )
    return float(altaz.alt.deg), float(altaz.az.deg)


def _vector_radec(vector: object) -> tuple[float, float]:
    import numpy as np

    array = np.asarray(vector, dtype=float)
    unit = array / np.linalg.norm(array)
    ra = math.degrees(math.atan2(unit[1], unit[0])) % 360.0
    dec = math.degrees(math.asin(float(np.clip(unit[2], -1.0, 1.0))))
    return ra, dec


def _separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dra = math.radians(ra2 - ra1)
    num = math.hypot(
        math.cos(p2) * math.sin(dra),
        math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dra),
    )
    den = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dra)
    return math.degrees(math.atan2(num, den))
