"""Pins the measured numbers cited in ``docs/accuracy_budget.md`` (§2.5).

Each test mirrors one budget entry so the document cannot silently drift
from the code: if an implementation change moves a floor or breaks a
scaling law, the budget must be re-measured and re-published.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from sglseti.ephemeris import AstropyEphemeris
from sglseti.geometry import Tusay2022Eq57V1, compute_relay_solution
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    Observer,
    Role,
    Target,
)
from sglseti.providers import (
    clear_provider_cache,
    register_programmatic_observer,
    unregister_programmatic_observer,
)

pytest.importorskip("jplephem")

KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / (
    "de440s_excerpt_2010-2035.bsp"
)
MODEL = Tusay2022Eq57V1()


def wolf359() -> Target:
    return Target(
        target_id="wolf-359",
        display_name="Wolf 359",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=164.1205036,
            dec_deg=7.0147231,
            parallax_mas=415.1794,
            pm_ra_cosdec_mas_per_yr=-3866.338,
            pm_dec_mas_per_yr=-2699.215,
            radial_velocity_km_s=19.57,
            reference_epoch_jyear=2000.0,
            reference_epoch_scale="tcb",
            source="Gaia EDR3 via SIMBAD; see wolf359_crossing_reference.py",
        ),
    )


@pytest.fixture(scope="module")
def kernel_ephemeris() -> AstropyEphemeris:
    return AstropyEphemeris(
        EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL))
    )


def _separation_mas(a, b) -> float:
    return float(
        SkyCoord(a.los_icrs_ra_deg * u.deg, a.los_icrs_dec_deg * u.deg)
        .separation(SkyCoord(b.los_icrs_ra_deg * u.deg, b.los_icrs_dec_deg * u.deg))
        .to_value(u.mas)
    )


def test_builtin_vs_kernel_relay_pointing_floor(kernel_ephemeris) -> None:
    """Budget §5: relay pointing floor <= 0.02 mas despite ~119 km absolute
    ephemeris differences — the geometry uses the Earth-Sun RELATIVE vector,
    where the analytic series' shared barycentric error cancels."""
    clear_provider_cache()
    builtin = AstropyEphemeris()
    worst = 0.0
    for z_au in (550.0, 2500.0):
        for jyear in (2013.0, 2016.5, 2021.85, 2025.2, 2029.9):
            time = Time(jyear, format="jyear", scale="tdb")
            common = dict(
                target=wolf359(),
                observation_time=time,
                z_au=z_au,
                role=Role.ANTIPODE,
                observer=Observer.earth_center(),
                model=MODEL,
            )
            worst = max(
                worst,
                _separation_mas(
                    compute_relay_solution(ephemeris=builtin, **common),
                    compute_relay_solution(ephemeris=kernel_ephemeris, **common),
                ),
            )
    assert worst < 0.02  # measured: 0.014 mas


def test_tx_epoch_amplification_scaling(kernel_ephemeris) -> None:
    """Budget §3: the tx-antipode offset equals mu * 2d/c to 1 percent."""
    clear_provider_cache()
    time = Time(2015.68, format="jyear", scale="tdb")
    common = dict(
        target=wolf359(),
        observation_time=time,
        z_au=665.0,
        observer=Observer.earth_center(),
        ephemeris=kernel_ephemeris,
        model=MODEL,
    )
    tx = compute_relay_solution(role=Role.TX, **common)
    antipode = compute_relay_solution(role=Role.ANTIPODE, **common)
    measured_arcsec = _separation_mas(tx, antipode) / 1000.0
    mu_arcsec_per_yr = math.hypot(-3866.338, -2699.215) / 1000.0
    predicted_arcsec = (
        mu_arcsec_per_yr * 2.0 * tx.direction.target_light_time_days / 365.25
    )
    assert measured_arcsec == pytest.approx(predicted_arcsec, rel=0.01)
    assert 70.0 < measured_arcsec < 80.0  # ~74 arcsec for Wolf 359


def test_spacecraft_displacement_scaling(kernel_ephemeris) -> None:
    """Budget §2: a cross-line-of-sight displacement maps to delta/rho."""
    clear_provider_cache()
    time = Time(2015.68, format="jyear", scale="tdb")
    common = dict(
        target=wolf359(),
        observation_time=time,
        z_au=550.0,
        role=Role.ANTIPODE,
        ephemeris=kernel_ephemeris,
        model=MODEL,
    )
    earth_solution = compute_relay_solution(
        observer=Observer.earth_center(), **common
    )
    line_of_sight = np.array(earth_solution.relay_barycentric_au) - np.array(
        earth_solution.observer_barycentric_au
    )
    rho_au = float(np.linalg.norm(line_of_sight))
    line_of_sight /= rho_au
    perpendicular = np.cross(line_of_sight, [0.0, 0.0, 1.0])
    perpendicular /= np.linalg.norm(perpendicular)
    offset = 0.01 * perpendicular
    register_programmatic_observer(
        "budget-l2ish",
        lambda t: kernel_ephemeris.earth_barycentric_au(t) + offset,
    )
    try:
        spacecraft_solution = compute_relay_solution(
            observer=Observer.programmatic("budget-l2ish", identity="budget-demo"),
            **common,
        )
    finally:
        unregister_programmatic_observer("budget-l2ish")
    measured_arcsec = _separation_mas(earth_solution, spacecraft_solution) / 1000.0
    predicted_arcsec = math.degrees(0.01 / rho_au) * 3600.0
    assert measured_arcsec == pytest.approx(predicted_arcsec, rel=0.005)
    assert measured_arcsec == pytest.approx(3.76, abs=0.05)


def test_solar_motion_light_time_class(kernel_ephemeris) -> None:
    """Budget §1/§5: the neglected solar-motion class is bounded by v_sun/c
    (~11 mas), consistent with the measured Horizons light-time residual."""
    speeds_km_s = []
    for jyear in np.linspace(2013.0, 2030.0, 40):
        t1 = Time(jyear, format="jyear", scale="tdb")
        t2 = Time(jyear + 0.01, format="jyear", scale="tdb")
        delta_au = kernel_ephemeris.sun_barycentric_au(
            t2
        ) - kernel_ephemeris.sun_barycentric_au(t1)
        speeds_km_s.append(
            float(np.linalg.norm(delta_au)) * 149_597_870.7 / (0.01 * 365.25 * 86_400.0)
        )
    bound_mas = max(speeds_km_s) / 299_792.458 * 206_265.0 * 1000.0
    assert 5.0 < bound_mas < 15.0  # measured: ~11 mas


def test_site_parallax_scale() -> None:
    """Budget §2: topocentric parallax at z = 550 AU is in the 1-20 mas band."""
    clear_provider_cache()
    builtin = AstropyEphemeris()
    time = Time(2021.85, format="jyear", scale="tdb")
    common = dict(
        target=wolf359(),
        observation_time=time,
        z_au=550.0,
        role=Role.ANTIPODE,
        ephemeris=builtin,
        model=MODEL,
    )
    geocentric = compute_relay_solution(observer=Observer.earth_center(), **common)
    topocentric = compute_relay_solution(
        observer=Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43),
        **common,
    )
    parallax_mas = _separation_mas(geocentric, topocentric)
    assert 1.0 < parallax_mas < 20.0
