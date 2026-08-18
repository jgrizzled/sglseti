"""Geometry core: the ``tusay2022_eq5_7_v1`` model and relay projection.

Implements the frozen Phase 0 contract (docs/science/geometry_models.md,
ADR-0001):

- catalog direction epochs are SSB light-arrival epochs
  (``antipode: u=t_o``, ``rx: u=t_o-2z/c``, ``tx: u=t_o+2d/c``); physical
  target-event epochs are diagnostics and are NEVER passed to catalog
  propagation;
- the declared target distance ``d`` is the SSB-target distance of the
  arrival-indexed catalog state at ``u = t_o`` (i.e. the propagated
  coordinate distance at the antipode epoch) — a declared approximation, not
  a silent read;
- the relay locus is ``P = S(t_o) - z * a(u_role)`` and the line of sight is
  ``unit(P - O(t_o))``, both in barycentric ICRS (Tusay et al. 2022 eq. 5
  with the role-corrected direction);
- validity: ``z > d/10`` is invalid (published model bound); ``z`` below the
  solar focal minimum, propagation spans beyond ±75 yr, and a flagged
  missing radial velocity (propagated as zero, never silently) degrade with
  machine-readable warning codes.

The observer's barycentric position is the ephemeris Earth barycenter plus
the site's GCRS position vector treated as an ICRS-axis offset (< 1 mas
effect; validated against the Phase 0 reference script).

This module computes; it never reads YAML, writes files, or applies planning
rules. Astropy is imported normally at module level (unlike the validation
layers) — this is the geometry-heavy module.
"""

from __future__ import annotations

import math
import warnings as _warnings
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from astropy import units as u
from astropy.coordinates import (
    CIRS,
    AltAz,
    Distance,
    EarthLocation,
    SkyCoord,
)
from astropy.time import Time, TimeDelta

from .ephemeris import Ephemeris, offline_resources
from .models import (
    DirectionSolution,
    Observer,
    ObserverKind,
    Role,
    Target,
    TargetEventKind,
    Validity,
)

__all__ = [
    "C_AU_PER_DAY",
    "PROPAGATION_SPAN_WARN_YEARS",
    "SOLAR_FOCAL_MIN_AU",
    "Z_OVER_D_INVALID_FRACTION",
    "GeometryModel",
    "MotionRates",
    "RelaySolution",
    "Tusay2022Eq57V1",
    "altaz_apparent",
    "cirs_apparent",
    "compute_relay_solution",
    "motion_rates",
    "observer_barycentric_au",
]

#: Speed of light in AU/day from defining constants (matches the fixtures).
C_AU_PER_DAY = 299_792_458 * 86_400 / 149_597_870_700

#: Solar minimum focal distance (tests/data/reference/solar_focal_distance.yaml).
SOLAR_FOCAL_MIN_AU = 547.7575534823646

#: Tusay et al. restrict probe placement to a tenth of the Sun-star distance.
Z_OVER_D_INVALID_FRACTION = 0.1

#: Preliminary linear-motion validity bound (geometry_models.md §5).
PROPAGATION_SPAN_WARN_YEARS = 75.0

_WARN_BELOW_FOCAL = "below_solar_focal_minimum"
_WARN_LONG_SPAN = "long_propagation_span"
_WARN_MISSING_RV = "missing_radial_velocity"
_WARN_Z_BEYOND_BOUND = "relay_beyond_model_bound"


@runtime_checkable
class GeometryModel(Protocol):
    """A versioned role model producing propagated target directions."""

    model_id: str
    model_version: str

    def target_direction(
        self,
        target: Target,
        observation_time: Time,
        relay_distance_au: float,
        role: Role,
        ephemeris: Ephemeris,
    ) -> DirectionSolution: ...


@dataclass(frozen=True)
class RelaySolution:
    """A locus geometry result: direction solution plus relay projection.

    All vectors are barycentric ICRS in AU at the observation epoch. The
    line of sight is geometric (no aberration or light deflection applied);
    apparent products are separate, explicitly labeled computations.
    """

    direction: DirectionSolution
    observation_time: Time
    observer: Observer
    ephemeris_id: str
    z_au: float
    sun_barycentric_au: tuple[float, float, float]
    observer_barycentric_au: tuple[float, float, float]
    relay_barycentric_au: tuple[float, float, float]
    los_icrs_ra_deg: float
    los_icrs_dec_deg: float
    rho_au: float
    frame: str = "icrs"
    correction: str = "geometric"


@dataclass(frozen=True)
class MotionRates:
    """Finite-difference angular rates of the geometric line of sight."""

    rate_ra_cosdec_arcsec_per_hr: float
    rate_dec_arcsec_per_hr: float
    step_s: float
    method: str = "central_finite_difference"


class Tusay2022Eq57V1:
    """The reviewed v1 role model (Tusay et al. 2022 eqs. 5-7)."""

    model_id = "tusay2022_eq5_7_v1"
    model_version = "1.0.0"

    def target_direction(
        self,
        target: Target,
        observation_time: Time,
        relay_distance_au: float,
        role: Role,
        ephemeris: Ephemeris,  # unused: this model neglects Solar motion
    ) -> DirectionSolution:
        del ephemeris
        z_au = float(relay_distance_au)
        if z_au <= 0.0 or not math.isfinite(z_au):
            raise ValueError(f"relay distance must be positive and finite, got {z_au}")
        warnings: list[str] = []
        catalog = _catalog_coord(target, warnings)

        t_tdb = observation_time.tdb
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            at_t_o = catalog.apply_space_motion(new_obstime=t_tdb)
        warnings.extend(f"astropy:{w.message}" for w in caught)

        d_au = float(at_t_o.distance.to_value(u.au))
        d_days = d_au / C_AU_PER_DAY
        z_days = z_au / C_AU_PER_DAY

        if role is Role.ANTIPODE:
            catalog_epoch = t_tdb
            target_event_epoch = t_tdb - TimeDelta(d_days, format="jd")
            target_event_kind = TargetEventKind.APPARENT_STATE
            solar_lens_epoch = t_tdb
            propagated = at_t_o
        elif role is Role.RX:
            catalog_epoch = t_tdb - TimeDelta(2.0 * z_days, format="jd")
            # Physical emission diagnostic: one further d/c earlier. Never an
            # input to apply_space_motion (double retardation).
            target_event_epoch = catalog_epoch - TimeDelta(d_days, format="jd")
            target_event_kind = TargetEventKind.EMISSION
            solar_lens_epoch = catalog_epoch
            propagated = None
        else:
            catalog_epoch = t_tdb + TimeDelta(2.0 * d_days, format="jd")
            # Physical arrival diagnostic: t_o + d/c under rho = z.
            target_event_epoch = t_tdb + TimeDelta(d_days, format="jd")
            target_event_kind = TargetEventKind.ARRIVAL
            solar_lens_epoch = t_tdb  # (z - rho)/c cancels under rho = z
            propagated = None

        if propagated is None:
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                propagated = catalog.apply_space_motion(new_obstime=catalog_epoch)
            warnings.extend(f"astropy:{w.message}" for w in caught)

        validity = Validity.VALID
        if any(w == _WARN_MISSING_RV for w in warnings):
            validity = Validity.DEGRADED
        if z_au < SOLAR_FOCAL_MIN_AU:
            warnings.append(_WARN_BELOW_FOCAL)
        span_years = abs((catalog_epoch - catalog.obstime.tdb).to_value(u.yr))
        if span_years > PROPAGATION_SPAN_WARN_YEARS:
            warnings.append(_WARN_LONG_SPAN)
            validity = Validity.DEGRADED if validity is Validity.VALID else validity
        if z_au > Z_OVER_D_INVALID_FRACTION * d_au:
            warnings.append(_WARN_Z_BEYOND_BOUND)
            validity = Validity.INVALID

        return DirectionSolution(
            model_id=self.model_id,
            model_version=self.model_version,
            role=role,
            observation_epoch=t_tdb,
            catalog_direction_epoch=catalog_epoch,
            relay_event_epoch_approx=t_tdb - TimeDelta(z_days, format="jd"),
            solar_lens_epoch_approx=solar_lens_epoch,
            target_event_epoch_approx=target_event_epoch,
            target_event_kind=target_event_kind,
            target_light_time_days=d_days,
            sun_relay_light_time_days=z_days,
            observer_relay_light_time_days_approx=z_days,  # rho = z assumed
            target_direction_icrs_ra_deg=float(propagated.ra.deg),
            target_direction_icrs_dec_deg=float(propagated.dec.deg),
            validity=validity,
            warnings=tuple(warnings),
        )


def _catalog_coord(target: Target, warnings: list[str]) -> SkyCoord:
    """Build the catalog SkyCoord honoring the declared reference scale.

    A flagged missing radial velocity propagates as zero with an explicit
    warning and degraded validity — never silently.
    """
    state = target.astrometry
    if state.parallax_mas is not None:
        distance = Distance(parallax=state.parallax_mas * u.mas)
    else:
        assert state.distance_pc is not None
        distance = Distance(state.distance_pc * u.pc)
    radial_velocity = state.radial_velocity_km_s
    if radial_velocity is None:
        warnings.append(_WARN_MISSING_RV)
        radial_velocity = 0.0
    reference_epoch = Time(
        state.reference_epoch_jyear,
        format="jyear",
        scale=state.reference_epoch_scale,
    )
    return SkyCoord(
        ra=state.ra_deg * u.deg,
        dec=state.dec_deg * u.deg,
        distance=distance,
        pm_ra_cosdec=state.pm_ra_cosdec_mas_per_yr * u.mas / u.yr,
        pm_dec=state.pm_dec_mas_per_yr * u.mas / u.yr,
        radial_velocity=radial_velocity * u.km / u.s,
        obstime=reference_epoch,
        frame="icrs",
    )


def observer_barycentric_au(
    observer: Observer, time: Time, ephemeris: Ephemeris
) -> np.ndarray:
    """Barycentric ICRS position of the observer in AU."""
    earth: np.ndarray = np.asarray(ephemeris.earth_barycentric_au(time), dtype=float)
    if observer.kind is ObserverKind.EARTH_CENTER:
        return earth
    assert observer.longitude_deg is not None
    location = EarthLocation.from_geodetic(
        lon=observer.longitude_deg * u.deg,
        lat=observer.latitude_deg * u.deg,
        height=observer.height_m * u.m,
    )
    with offline_resources():
        site_gcrs = location.get_gcrs_posvel(time)[0]
    site_offset: np.ndarray = np.asarray(site_gcrs.xyz.to_value(u.au), dtype=float)
    result: np.ndarray = earth + site_offset
    return result


def _unit_vector(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    vector: np.ndarray = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    return vector


def _tuple3(vector: np.ndarray) -> tuple[float, float, float]:
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _radec_deg(vector: np.ndarray) -> tuple[float, float]:
    unit = vector / np.linalg.norm(vector)
    ra = math.degrees(math.atan2(unit[1], unit[0])) % 360.0
    dec = math.degrees(math.asin(float(np.clip(unit[2], -1.0, 1.0))))
    return ra, dec


def compute_relay_solution(
    *,
    target: Target,
    observation_time: Time,
    z_au: float,
    role: Role,
    observer: Observer,
    ephemeris: Ephemeris,
    model: GeometryModel,
) -> RelaySolution:
    """Compute one locus geometry: direction, relay position, line of sight."""
    with offline_resources():
        direction = model.target_direction(
            target, observation_time, z_au, role, ephemeris
        )
        sun = ephemeris.sun_barycentric_au(observation_time)
        obs = observer_barycentric_au(observer, observation_time, ephemeris)
    target_hat = _unit_vector(
        direction.target_direction_icrs_ra_deg,
        direction.target_direction_icrs_dec_deg,
    )
    sun = np.asarray(sun, dtype=float)
    relay = sun - z_au * target_hat
    los = relay - obs
    los_ra, los_dec = _radec_deg(los)
    return RelaySolution(
        direction=direction,
        observation_time=observation_time,
        observer=observer,
        ephemeris_id=ephemeris.ephemeris_id,
        z_au=z_au,
        sun_barycentric_au=_tuple3(sun),
        observer_barycentric_au=_tuple3(obs),
        relay_barycentric_au=_tuple3(relay),
        los_icrs_ra_deg=los_ra,
        los_icrs_dec_deg=los_dec,
        rho_au=float(np.linalg.norm(los)),
    )


def _relay_skycoord(solution: RelaySolution) -> SkyCoord:
    x, y, z = solution.relay_barycentric_au
    return SkyCoord(
        x=x * u.au, y=y * u.au, z=z * u.au, frame="icrs", representation_type="cartesian"
    )


def _site_location(observer: Observer) -> EarthLocation:
    if observer.kind is not ObserverKind.SITE:
        raise ValueError("apparent AltAz products require a terrestrial site observer")
    assert observer.longitude_deg is not None
    return EarthLocation.from_geodetic(
        lon=observer.longitude_deg * u.deg,
        lat=observer.latitude_deg * u.deg,
        height=observer.height_m * u.m,
    )


def cirs_apparent(solution: RelaySolution) -> tuple[float, float]:
    """Apparent CIRS RA/Dec of the relay for the solution's observer.

    Topocentric CIRS for a site observer, geocentric for Earth center. The
    transform is astropy's full barycentric-cartesian path (parallax and
    aberration handled by the frame machinery), labeled apparent-approximate
    per the model documentation.
    """
    location = (
        None
        if solution.observer.kind is ObserverKind.EARTH_CENTER
        else _site_location(solution.observer)
    )
    with offline_resources():
        cirs = _relay_skycoord(solution).transform_to(
            CIRS(obstime=solution.observation_time, location=location)
        )
    return float(cirs.ra.deg), float(cirs.dec.deg)


def altaz_apparent(solution: RelaySolution) -> tuple[float, float]:
    """Apparent altitude/azimuth of the relay (refraction disabled)."""
    location = _site_location(solution.observer)
    with offline_resources():
        altaz = _relay_skycoord(solution).transform_to(
            AltAz(obstime=solution.observation_time, location=location)
        )
    return float(altaz.alt.deg), float(altaz.az.deg)


def motion_rates(
    *,
    target: Target,
    observation_time: Time,
    z_au: float,
    role: Role,
    observer: Observer,
    ephemeris: Ephemeris,
    model: GeometryModel,
    step_s: float = 60.0,
) -> MotionRates:
    """Central finite-difference rates of the geometric ICRS line of sight."""
    if step_s <= 0.0:
        raise ValueError(f"step_s must be positive, got {step_s}")
    half = TimeDelta(step_s / 2.0, format="sec")
    before = compute_relay_solution(
        target=target,
        observation_time=observation_time - half,
        z_au=z_au,
        role=role,
        observer=observer,
        ephemeris=ephemeris,
        model=model,
    )
    after = compute_relay_solution(
        target=target,
        observation_time=observation_time + half,
        z_au=z_au,
        role=role,
        observer=observer,
        ephemeris=ephemeris,
        model=model,
    )
    coord_before = SkyCoord(
        ra=before.los_icrs_ra_deg * u.deg, dec=before.los_icrs_dec_deg * u.deg
    )
    coord_after = SkyCoord(
        ra=after.los_icrs_ra_deg * u.deg, dec=after.los_icrs_dec_deg * u.deg
    )
    d_ra_cosdec, d_dec = coord_before.spherical_offsets_to(coord_after)
    hours = step_s / 3600.0
    return MotionRates(
        rate_ra_cosdec_arcsec_per_hr=float(d_ra_cosdec.to_value(u.arcsec)) / hours,
        rate_dec_arcsec_per_hr=float(d_dec.to_value(u.arcsec)) / hours,
        step_s=step_s,
    )
