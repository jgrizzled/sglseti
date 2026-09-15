"""Independent reference for the Wolf 359 beam-crossing fixture (§2.5).

Reproduces the geometry of Gillon, Burdanov & Wright 2022 (MNRAS 513:L18,
arXiv:2111.05334): a hypothesized probe on the Sun-Wolf 359 axis at
z = 665 AU transmits toward Wolf 359 (outbound link), and Earth crosses
the beam annulus near solar conjunction each early September.

This script is a no-abstraction astropy transcription — it imports nothing
from sglseti — of the ``sun_star_axis_v1`` outbound convention
(ADR-0003): the axis is anchored at the Sun's barycentric position along
the catalog direction propagated to the tx aim epoch ``u = t + 2 d / c``
(``d`` = the SSB coordinate distance of the state propagated to ``t``),
and the impact parameter is the Earth's perpendicular distance to that
axis. Positions come from the pinned DE440s excerpt kernel
(``tests/data/kernels/de440s_excerpt_2010-2035.bsp``) so the frozen values
are tied to checksummed data, not to a library's analytic series.

It freezes, per campaign year (2015 TRAPPIST-South, 2019
SPECULOOS-South):

- the minimum-impact-parameter crossing epoch and ``b_min`` (solar radii);
- the impact parameter at the PAPER'S published crossing epoch — the
  documented disagreement (notes/published_sgl_search_validation.md): at
  the published times the Earth sits well outside the paper's own
  1.1 R_sun beam annulus, so the offset is an explicit expected result,
  not a bug to reconcile;
- the tx line of sight from the TRAPPIST-South site at the published 2015
  epoch, for publication consistency against the paper's field center.

Run from the repository root to regenerate the frozen fixture:

    uv run python tests/data/reference/wolf359_crossing_reference.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import yaml
from astropy import units as u
from astropy.coordinates import (
    Distance,
    EarthLocation,
    SkyCoord,
    get_body_barycentric,
    solar_system_ephemeris,
)
from astropy.time import Time, TimeDelta
from astropy.utils import iers

KERNEL = Path(__file__).resolve().parents[1] / "kernels" / ("de440s_excerpt_2010-2035.bsp")

C_AU_PER_DAY = 299_792_458 * 86_400 / 149_597_870_700
KM_PER_AU = 149_597_870.700
SOLAR_RADIUS_KM = 695_700.0
Z_AU = 665.0

#: Gaia EDR3 astrometry via SIMBAD (queried 2026-08-18), ICRS
#: J2000-propagated, as recorded in notes/published_sgl_search_validation.md.
WOLF359 = {
    "ra_deg": 164.1205036,
    "dec_deg": 7.0147231,
    "parallax_mas": 415.1794,
    "pm_ra_cosdec_mas_per_yr": -3866.338,
    "pm_dec_mas_per_yr": -2699.215,
    "radial_velocity_km_s": 19.57,
    "reference_epoch_jyear": 2000.0,
    "reference_epoch_scale": "tcb",
}

#: Published crossing epochs (paper Sec. 3.1): JD 2457270.82 = 2015 Sep 5
#: 07:41 UT; "around 1h45 UT" 2019 Sep 5.
PUBLISHED = {
    2015: {"crossing_utc": "2015-09-05T07:41:00", "campaign": "TRAPPIST-South"},
    2019: {"crossing_utc": "2019-09-05T01:45:00", "campaign": "SPECULOOS-South"},
}
PUBLISHED_ANNULUS_RSUN = 1.1
PUBLISHED_FIELD_CENTER = {  # 22h56m20.81s, -06d59'28.4"
    "ra_deg": (22.0 + 56.0 / 60.0 + 20.81 / 3600.0) * 15.0,
    "dec_deg": -(6.0 + 59.0 / 60.0 + 28.4 / 3600.0),
}
TRAPPIST_SOUTH = {"lon_deg": -70.7403, "lat_deg": -29.2563, "height_m": 2347.0}


def catalog() -> SkyCoord:
    return SkyCoord(
        ra=WOLF359["ra_deg"] * u.deg,
        dec=WOLF359["dec_deg"] * u.deg,
        distance=Distance(parallax=WOLF359["parallax_mas"] * u.mas),
        pm_ra_cosdec=WOLF359["pm_ra_cosdec_mas_per_yr"] * u.mas / u.yr,
        pm_dec=WOLF359["pm_dec_mas_per_yr"] * u.mas / u.yr,
        radial_velocity=WOLF359["radial_velocity_km_s"] * u.km / u.s,
        obstime=Time(
            WOLF359["reference_epoch_jyear"],
            format="jyear",
            scale=WOLF359["reference_epoch_scale"],
        ),
        frame="icrs",
    )


def axis_hat(time: Time) -> np.ndarray:
    """Outbound (tx-aim) axis direction: catalog propagated to u = t + 2d/c."""
    t_tdb = time.tdb
    at_t = catalog().apply_space_motion(new_obstime=t_tdb)
    d_days = float(at_t.distance.to_value(u.au)) / C_AU_PER_DAY
    aimed = catalog().apply_space_motion(new_obstime=t_tdb + TimeDelta(2.0 * d_days, format="jd"))
    ra = math.radians(float(aimed.ra.deg))
    dec = math.radians(float(aimed.dec.deg))
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def body_au(body: str, time: Time) -> np.ndarray:
    with solar_system_ephemeris.set(str(KERNEL)):
        return np.asarray(get_body_barycentric(body, time).xyz.to_value(u.au), dtype=float)


def impact_rsun(time: Time) -> float:
    r = body_au("earth", time) - body_au("sun", time)
    a = axis_hat(time)
    perp = r - float(np.dot(r, a)) * a
    return float(np.linalg.norm(perp)) * KM_PER_AU / SOLAR_RADIUS_KM


def golden_minimize(fn, lo: float, hi: float, tol: float) -> float:
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    fc, fd = fn(c), fn(d)
    while (b - a) > tol:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - invphi * (b - a)
            fc = fn(c)
        else:
            a, c, fc = c, d, fd
            d = a + invphi * (b - a)
            fd = fn(d)
    return (a + b) / 2.0


def minimum_crossing(year: int) -> tuple[Time, float]:
    start = Time(f"{year}-08-01T00:00:00", scale="utc").tdb

    def b_at(offset_days: float) -> float:
        return impact_rsun(start + TimeDelta(offset_days, format="jd"))

    grid = np.arange(0.0, 61.0, 1.0)
    values = [b_at(o) for o in grid]
    k = int(np.argmin(values))
    offset = golden_minimize(
        b_at, grid[max(0, k - 1)], grid[min(len(grid) - 1, k + 1)], 5.0 / 86_400.0
    )
    time = start + TimeDelta(offset, format="jd")
    return time, b_at(offset)


def tx_pointing_from_trappist(time: Time) -> tuple[float, float]:
    a = axis_hat(time)
    relay = body_au("sun", time) - Z_AU * a
    location = EarthLocation.from_geodetic(
        lon=TRAPPIST_SOUTH["lon_deg"] * u.deg,
        lat=TRAPPIST_SOUTH["lat_deg"] * u.deg,
        height=TRAPPIST_SOUTH["height_m"] * u.m,
    )
    with iers.conf.set_temp("auto_download", False):
        site = np.asarray(location.get_gcrs_posvel(time)[0].xyz.to_value(u.au), dtype=float)
    observer = body_au("earth", time) + site
    los = relay - observer
    los /= np.linalg.norm(los)
    ra = math.degrees(math.atan2(los[1], los[0])) % 360.0
    dec = math.degrees(math.asin(float(np.clip(los[2], -1.0, 1.0))))
    return ra, dec


def main() -> None:
    years = {}
    for year, published in PUBLISHED.items():
        t_min, b_min = minimum_crossing(year)
        published_time = Time(published["crossing_utc"], scale="utc")
        years[year] = {
            "campaign": published["campaign"],
            "published_crossing_utc": published["crossing_utc"],
            "computed_crossing_utc": str(t_min.utc.isot),
            "computed_crossing_tdb_jd": float(t_min.tdb.jd),
            "computed_b_min_rsun": b_min,
            "offset_from_published_hours": float((t_min.tdb - published_time.tdb).to_value(u.h)),
            "b_at_published_epoch_rsun": impact_rsun(published_time),
        }
    ra_2015, dec_2015 = tx_pointing_from_trappist(
        Time(PUBLISHED[2015]["crossing_utc"], scale="utc")
    )
    output = {
        "generator": "tests/data/reference/wolf359_crossing_reference.py",
        "paper": "Gillon, Burdanov & Wright 2022, MNRAS 513:L18 (arXiv:2111.05334)",
        "method": (
            "independent no-sglseti astropy transcription of the "
            "sun_star_axis_v1 outbound convention on the pinned DE440s "
            "excerpt kernel"
        ),
        "kernel": KERNEL.name,
        "astrometry": dict(WOLF359),
        "relay_distance_au": Z_AU,
        "published_annulus_rsun": PUBLISHED_ANNULUS_RSUN,
        "published_field_center": dict(PUBLISHED_FIELD_CENTER),
        "trappist_south_site": dict(TRAPPIST_SOUTH),
        "tx_pointing_at_published_2015_epoch": {
            "ra_deg": ra_2015,
            "dec_deg": dec_2015,
        },
        "years": years,
    }
    path = Path(__file__).with_name("wolf359_crossing_reference.yaml")
    path.write_text(
        "# GENERATED by wolf359_crossing_reference.py — do not edit by hand.\n"
        + yaml.safe_dump(output, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {path}")
    for year, data in years.items():
        print(
            f"{year}: min b {data['computed_b_min_rsun']:.3f} Rsun at "
            f"{data['computed_crossing_utc']} "
            f"(published {data['published_crossing_utc']}, "
            f"offset {data['offset_from_published_hours']:+.1f} h, "
            f"b at published epoch {data['b_at_published_epoch_rsun']:.2f} Rsun)"
        )
    print(f"tx pointing 2015: {ra_2015:.5f}, {dec_2015:.5f}")


if __name__ == "__main__":
    main()
