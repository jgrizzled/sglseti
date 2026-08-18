from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Site, Target


class GeometryDependencyError(RuntimeError):
    pass


def _imports() -> dict[str, Any]:
    try:
        import astropy.units as u
        from astropy.constants import c
        from astropy.coordinates import (
            AltAz,
            CIRS,
            Distance,
            EarthLocation,
            ICRS,
            SkyCoord,
            get_body,
            get_body_barycentric,
            get_sun,
            solar_system_ephemeris,
        )
        from astropy.time import Time
        from astropy.utils import iers
    except ImportError as exc:
        raise GeometryDependencyError(
            "Astropy is required for planning. Install the project with "
            "'python -m pip install -e .'."
        ) from exc
    return locals()


@dataclass(frozen=True)
class ProbePoint:
    geometric_icrs: Any
    apparent_cirs: Any
    altaz: Any
    probe_icrs: Any
    heliocentric_range_au: float


@dataclass(frozen=True)
class EnvironmentAtPoint:
    sun_altitude_deg: float
    moon_separation_deg: float


class GeometryEngine:
    """Implements the approximate SGL relay loci in Tusay et al. (2022), Eq. 5-7.

    Roles are local to the Solar System:
      * antipode: no light-time role correction
      * transmitter: local relay transmits through the SGL to the target system
      * receiver: local relay receives through the SGL from the target system

    The model uses linear stellar space motion and a configured Solar System
    ephemeris. It is appropriate for search planning, but sub-arcsecond campaigns
    should independently validate binary barycenters, endpoint orbital motion,
    astrometric covariances, and ephemeris choices.
    """

    def __init__(self, ephemeris: str = "builtin", iers_auto_download: bool = True):
        a = _imports()
        self.a = a
        self.ephemeris = ephemeris
        a["iers"].conf.auto_download = iers_auto_download

    def time(self, value: str) -> Any:
        return self.a["Time"](value, scale="utc")

    def site_location(self, site: Site) -> Any:
        u = self.a["u"]
        return self.a["EarthLocation"].from_geodetic(
            lon=site.longitude_deg * u.deg,
            lat=site.latitude_deg * u.deg,
            height=site.elevation_m * u.m,
        )

    def target_coord(self, target: Target) -> Any:
        u = self.a["u"]
        Time = self.a["Time"]
        Distance = self.a["Distance"]
        SkyCoord = self.a["SkyCoord"]
        astro = target.astrometry
        return SkyCoord(
            ra=astro.ra_deg * u.deg,
            dec=astro.dec_deg * u.deg,
            distance=Distance(parallax=astro.parallax_mas * u.mas),
            pm_ra_cosdec=astro.pm_ra_cosdec_mas_per_yr * u.mas / u.yr,
            pm_dec=astro.pm_dec_mas_per_yr * u.mas / u.yr,
            radial_velocity=astro.radial_velocity_km_s * u.km / u.s,
            obstime=Time(astro.reference_epoch_jyear, format="jyear", scale="tdb"),
            frame="icrs",
        )

    def _target_unit_from_sun(self, target: Target, epoch: Any) -> np.ndarray:
        u = self.a["u"]
        get_body_barycentric = self.a["get_body_barycentric"]
        base = self.target_coord(target)
        propagated = base.apply_space_motion(new_obstime=epoch)
        with self.a["solar_system_ephemeris"].set(self.ephemeris):
            sun = get_body_barycentric("sun", epoch)
        star_xyz = propagated.cartesian.xyz.to_value(u.au)
        sun_xyz = sun.xyz.to_value(u.au)
        vector = np.asarray(star_xyz - sun_xyz, dtype=float)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            raise ValueError(f"Invalid propagated direction for target {target.target_id}.")
        return vector / norm

    def _direction_epoch(self, target: Target, role: str, z_au: float, obstime: Any) -> Any:
        u = self.a["u"]
        c = self.a["c"]
        if role == "antipode":
            return obstime
        if role == "receiver":
            return obstime - (2.0 * z_au * u.au / c).to(u.day)
        if role == "transmitter":
            at_time = self.target_coord(target).apply_space_motion(new_obstime=obstime)
            distance = at_time.distance
            return obstime + (2.0 * distance / c).to(u.day)
        raise ValueError(f"Unknown role: {role}")

    def probe_point(
        self,
        target: Target,
        role: str,
        z_au: float,
        obstime: Any,
        site_location: Any,
    ) -> ProbePoint:
        u = self.a["u"]
        SkyCoord = self.a["SkyCoord"]
        CIRS = self.a["CIRS"]
        AltAz = self.a["AltAz"]
        get_body_barycentric = self.a["get_body_barycentric"]

        if z_au <= 0:
            raise ValueError("z_au must be positive.")
        direction_epoch = self._direction_epoch(target, role, z_au, obstime)
        unit = self._target_unit_from_sun(target, direction_epoch)

        with self.a["solar_system_ephemeris"].set(self.ephemeris):
            sun = get_body_barycentric("sun", obstime)
            earth = get_body_barycentric("earth", obstime)

        sun_xyz = sun.xyz.to_value(u.au)
        probe_xyz = np.asarray(sun_xyz, dtype=float) - z_au * unit
        probe_icrs = SkyCoord(
            x=probe_xyz[0] * u.au,
            y=probe_xyz[1] * u.au,
            z=probe_xyz[2] * u.au,
            representation_type="cartesian",
            frame="icrs",
        )

        obsgeoloc, _ = site_location.get_gcrs_posvel(obstime)
        observer_xyz = earth.xyz.to_value(u.au) + obsgeoloc.xyz.to_value(u.au)
        los = probe_xyz - observer_xyz
        geometric_icrs = SkyCoord(
            x=los[0] * u.au,
            y=los[1] * u.au,
            z=los[2] * u.au,
            representation_type="cartesian",
            frame="icrs",
        )

        apparent_cirs = probe_icrs.transform_to(
            CIRS(obstime=obstime, location=site_location)
        )
        altaz = probe_icrs.transform_to(
            AltAz(obstime=obstime, location=site_location, pressure=0 * u.hPa)
        )
        return ProbePoint(
            geometric_icrs=geometric_icrs,
            apparent_cirs=apparent_cirs,
            altaz=altaz,
            probe_icrs=probe_icrs,
            heliocentric_range_au=z_au,
        )

    def environment(
        self, point: ProbePoint, obstime: Any, site_location: Any
    ) -> EnvironmentAtPoint:
        u = self.a["u"]
        AltAz = self.a["AltAz"]
        get_sun = self.a["get_sun"]
        get_body = self.a["get_body"]
        frame = AltAz(obstime=obstime, location=site_location, pressure=0 * u.hPa)
        sun_alt = get_sun(obstime).transform_to(frame).alt.to_value(u.deg)
        with self.a["solar_system_ephemeris"].set(self.ephemeris):
            moon = get_body("moon", obstime, location=site_location)
        moon_altaz = moon.transform_to(frame)
        moon_sep = point.altaz.separation(moon_altaz).to_value(u.deg)
        return EnvironmentAtPoint(
            sun_altitude_deg=float(sun_alt),
            moon_separation_deg=float(moon_sep),
        )

    def motion_rates(
        self,
        target: Target,
        role: str,
        z_au: float,
        obstime: Any,
        site_location: Any,
        delta_minutes: float = 15.0,
    ) -> tuple[float, float]:
        u = self.a["u"]
        dt = delta_minutes * u.min
        before = self.probe_point(target, role, z_au, obstime - dt, site_location)
        after = self.probe_point(target, role, z_au, obstime + dt, site_location)
        dlon, dlat = before.geometric_icrs.spherical_offsets_to(after.geometric_icrs)
        hours = (2.0 * dt).to_value(u.hour)
        return (
            float(dlon.to_value(u.arcsec) / hours),
            float(dlat.to_value(u.arcsec) / hours),
        )
