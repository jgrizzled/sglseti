"""Independent JPL Horizons cross-validation of Earth-based positions (§2.5).

The frozen fixture (``horizons_reference.yaml``, one-time online fetch
documented in ``horizons_reference.py``) carries DE441 barycentric ICRF
vectors for the Sun and the Earth geocenter, and astrometric solar RA/Dec
from the geocenter and from the Green Bank site. All tests here run
offline against those frozen values.

Measured agreements the tolerances are set from (3x-plus margins):

- pinned DE440s excerpt kernel vs Horizons DE441 vectors: sub-meter;
- astropy builtin analytic ephemeris vs Horizons: worst ~119 km;
- light-time-retarded solar direction (geocenter and site) vs Horizons
  astrometric: 0.002 / 0.009 mas — the full ephemeris + observer +
  direction pipeline, including the site GCRS offset, at the
  microarcsecond level;
- UNRETARDED geometric direction vs Horizons astrometric: up to ~9 mas —
  the Sun's barycentric motion over one light-time, i.e. the measured
  scale of the light-time term the geometric products deliberately omit.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time, TimeDelta
from support import load_reference_fixture

from sglseti.ephemeris import AstropyEphemeris, offline_resources
from sglseti.geometry import C_AU_PER_DAY, observer_barycentric_au
from sglseti.models import EphemerisAdapter, EphemerisSpec, Observer

FIXTURE = load_reference_fixture("horizons_reference.yaml")
KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / ("de440s_excerpt_2010-2035.bsp")
KM_PER_AU = 149_597_870.700

pytest.importorskip("jplephem")


@pytest.fixture(scope="module")
def kernel_ephemeris() -> AstropyEphemeris:
    return AstropyEphemeris(EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL)))


def _reference_vector(row: dict) -> np.ndarray:
    return np.array([row["x_au"], row["y_au"], row["z_au"]])


@pytest.mark.parametrize("body", ["sun", "earth"])
def test_pinned_kernel_matches_horizons_vectors(kernel_ephemeris, body: str) -> None:
    for row in FIXTURE[f"{body}_barycentric"]:
        time = Time(row["tdb_jd"], format="jd", scale="tdb")
        ours = getattr(kernel_ephemeris, f"{body}_barycentric_au")(time)
        delta_km = float(np.linalg.norm(ours - _reference_vector(row))) * KM_PER_AU
        assert delta_km < 0.1  # measured: sub-meter


@pytest.mark.parametrize("body", ["sun", "earth"])
def test_builtin_ephemeris_matches_horizons_vectors(body: str) -> None:
    builtin = AstropyEphemeris()
    for row in FIXTURE[f"{body}_barycentric"]:
        time = Time(row["tdb_jd"], format="jd", scale="tdb")
        with offline_resources():
            ours = getattr(builtin, f"{body}_barycentric_au")(time)
        delta_km = float(np.linalg.norm(ours - _reference_vector(row))) * KM_PER_AU
        assert delta_km < 500.0  # measured: worst ~119 km (analytic series)


def _sun_direction_separations_mas(
    kernel: AstropyEphemeris, observer: Observer, rows: list, *, retarded: bool
) -> list[float]:
    separations = []
    for row in rows:
        with offline_resources():
            time = Time(row["ut_jd"], format="jd", scale="utc").tdb
            observer_au = observer_barycentric_au(observer, time, kernel)
            sun_au = kernel.sun_barycentric_au(time)
            if retarded:
                light_time_days = float(np.linalg.norm(sun_au - observer_au)) / C_AU_PER_DAY
                sun_au = kernel.sun_barycentric_au(
                    time - TimeDelta(light_time_days, format="jd", scale="tdb")
                )
        los = sun_au - observer_au
        ra = math.degrees(math.atan2(los[1], los[0])) % 360.0
        dec = math.degrees(math.asin(float(los[2] / np.linalg.norm(los))))
        separations.append(
            float(
                SkyCoord(ra * u.deg, dec * u.deg)
                .separation(SkyCoord(row["ra_deg"] * u.deg, row["dec_deg"] * u.deg))
                .to_value(u.mas)
            )
        )
    return separations


def _green_bank() -> Observer:
    site = FIXTURE["green_bank_site"]
    return Observer.from_geodetic("green-bank", site["lon_deg"], site["lat_deg"], site["height_m"])


@pytest.mark.parametrize(
    ("rows_key", "observer_factory", "tolerance_mas"),
    [
        ("sun_astrometric_geocenter", Observer.earth_center, 0.1),
        # The site path additionally exercises the GCRS offset; its EOP
        # source (bundled IERS) drifts slightly across astropy-iers-data
        # releases, hence the wider bound (measured: 0.009 mas).
        ("sun_astrometric_green_bank", _green_bank, 0.5),
    ],
)
def test_retarded_direction_matches_horizons_astrometric(
    kernel_ephemeris, rows_key: str, observer_factory, tolerance_mas: float
) -> None:
    separations = _sun_direction_separations_mas(
        kernel_ephemeris, observer_factory(), FIXTURE[rows_key], retarded=True
    )
    assert max(separations) < tolerance_mas


def test_geometric_direction_differs_by_the_light_time_term(
    kernel_ephemeris,
) -> None:
    """The unretarded geometric direction sits ~mas from Horizons.

    This measures the light-time term the geometric products deliberately
    omit (the Sun's barycentric motion over ~499 s): small enough for
    every v1 pointing product, large enough that it must stay documented
    rather than silently absorbed. A drop to the microarcsecond level here
    would mean retardation crept into the geometric path — also a
    regression.
    """
    separations = _sun_direction_separations_mas(
        kernel_ephemeris,
        Observer.earth_center(),
        FIXTURE["sun_astrometric_geocenter"],
        retarded=False,
    )
    assert max(separations) < 15.0
    assert max(separations) > 0.1
