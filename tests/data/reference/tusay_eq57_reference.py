#!/usr/bin/env python3
"""Straight-line transcription of Tusay et al. (2022) equations 5-7.

This is a Phase 0 reference oracle, independent of sgl-search-planner and of
the sglseti geometry engine: a deliberately simple, no-abstraction astropy
implementation of the published equations, used to freeze the Alpha Centauri
2021-11-06 fixture. The Phase 4 engine must reproduce these values through
its own code path within the fixture tolerance.

Published model (arXiv:2206.14807, section I.3.2):
    eq. 5:  P = S(t) - z * x(t)
    eq. 6:  P_tx = S(t) - z * x(t + 2d/c)
    eq. 7:  P_rx = S(t) - z * x(t - 2z/c)
where S(t) is the barycentric Solar position, x(t) the target's apparent
(arrival-indexed) unit direction, z the Sun-relay distance, and d the target
distance. Per the reconciliation note, x's time argument is an SSB
light-arrival epoch, so x(u) is evaluated with catalog space-motion
propagation (SkyCoord.apply_space_motion), never with a physical emission
epoch.

Documented approximations of this reference script (all sub-arcsecond at the
fixture tolerance of 2 arcsec):
- x is the SSB-origin direction rather than Sun-origin (~7 mas at 1.35 pc
  at this epoch, bounded by ~8 mas);
- observer barycentric position = Earth barycenter + GCRS site vector
  treated as ICRS-axis offset (< mas);
- astropy built-in ephemeris and bundled IERS tables, offline;
- catalog reference epoch scale treated as TDB (sub-mas at this tolerance);
- time arguments t_o +/- offsets applied on the TDB scale.

Run:  python tusay_eq57_reference.py
"""

from __future__ import annotations

import json

import numpy as np
from astropy import units as u
from astropy.coordinates import (
    Distance,
    EarthLocation,
    SkyCoord,
    get_body_barycentric,
)
from astropy.time import Time
from astropy.utils import iers

iers.conf.auto_download = False

# --- Fixture inputs (sources documented in alpha_cen_2021-11-06.yaml) -------

# Alpha Cen A astrometry, SIMBAD display captured 2026-08-17:
# position/PM van Leeuwen 2007 (2007A&A...474..653V), parallax Perryman et
# al. 1997 (1997A&A...323L..49P), RV 2021MNRAS.506..150B. ICRS, epoch J2000.
ALPHA_CEN_A = {
    "ra_deg": (14.0 + 39.0 / 60.0 + 36.49400 / 3600.0) * 15.0,
    "dec_deg": -(60.0 + 50.0 / 60.0 + 2.3737 / 3600.0),
    "parallax_mas": 742.12,
    "pm_ra_cosdec_mas_per_yr": -3679.25,
    "pm_dec_mas_per_yr": 473.67,
    "radial_velocity_km_s": -15.252,
    "reference_epoch_jyear": 2000.0,
}

# Green Bank Telescope site (NRAO): 38d25m59.24s N, 79d50m23.41s W, 807.43 m.
GBT = EarthLocation.from_geodetic(
    lon=-(79.0 + 50.0 / 60.0 + 23.41 / 3600.0) * u.deg,
    lat=(38.0 + 25.0 / 60.0 + 59.24 / 3600.0) * u.deg,
    height=807.43 * u.m,
)

# Representative epoch for the published UT 2021 November 6 GBT session (the
# paper does not tabulate scan times; tolerance absorbs intra-day motion).
T_O = Time("2021-11-06T00:00:00", scale="utc")

Z_VALUES_AU = [550.0, 1000.0, 2500.0]


def catalog_coord() -> SkyCoord:
    return SkyCoord(
        ra=ALPHA_CEN_A["ra_deg"] * u.deg,
        dec=ALPHA_CEN_A["dec_deg"] * u.deg,
        distance=Distance(parallax=ALPHA_CEN_A["parallax_mas"] * u.mas),
        pm_ra_cosdec=ALPHA_CEN_A["pm_ra_cosdec_mas_per_yr"] * u.mas / u.yr,
        pm_dec=ALPHA_CEN_A["pm_dec_mas_per_yr"] * u.mas / u.yr,
        radial_velocity=ALPHA_CEN_A["radial_velocity_km_s"] * u.km / u.s,
        obstime=Time(ALPHA_CEN_A["reference_epoch_jyear"], format="jyear", scale="tdb"),
        frame="icrs",
    )


def observer_barycentric(t: Time) -> u.Quantity:
    earth = get_body_barycentric("earth", t)
    site_gcrs = GBT.get_gcrs_posvel(t)[0]
    return earth.xyz.to(u.au) + site_gcrs.xyz.to(u.au)


def direction_radec(vec: u.Quantity) -> tuple[float, float]:
    x, y, z = (vec / np.linalg.norm(vec)).value
    ra = float(np.degrees(np.arctan2(y, x)) % 360.0)
    dec = float(np.degrees(np.arcsin(z)))
    return ra, dec


def main() -> None:
    coord = catalog_coord()
    d = coord.distance.to(u.au)
    c_au_per_day = 173.144632674240 * u.au / u.day
    two_d_over_c = (2.0 * d / c_au_per_day).to(u.day)

    t_o_tdb = T_O.tdb
    sun = get_body_barycentric("sun", T_O).xyz.to(u.au)
    obs = observer_barycentric(T_O)

    out: dict = {
        "t_o_utc": T_O.isot,
        "t_o_tdb_jd": float(t_o_tdb.jd),
        "d_au": float(d.value),
        "two_d_over_c_days": float(two_d_over_c.value),
        "sun_barycentric_au": [float(v) for v in sun.value],
        "observer_barycentric_au": [float(v) for v in obs.value],
        "roles": {},
    }

    for z_au in Z_VALUES_AU:
        z = z_au * u.au
        two_z_over_c = (2.0 * z / c_au_per_day).to(u.day)
        epochs = {
            "antipode": t_o_tdb,
            "rx": t_o_tdb - two_z_over_c,
            "tx": t_o_tdb + two_d_over_c,
        }
        for role, epoch in epochs.items():
            moved = coord.apply_space_motion(new_obstime=epoch)
            x_hat = moved.icrs.represent_as("unitspherical").to_cartesian().xyz.value
            relay = sun - z * x_hat
            los = relay - obs
            los_ra, los_dec = direction_radec(los)
            dir_ra, dir_dec = direction_radec(x_hat * u.au)
            out["roles"][f"{role}_z{z_au:g}"] = {
                "z_au": z_au,
                "catalog_epoch_tdb_jd": float(epoch.jd),
                "target_dir_ra_deg": round(dir_ra, 9),
                "target_dir_dec_deg": round(dir_dec, 9),
                "los_ra_deg": round(los_ra, 9),
                "los_dec_deg": round(los_dec, 9),
                "rho_au": float(np.linalg.norm(los.value)),
            }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
