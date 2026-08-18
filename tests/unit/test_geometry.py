from __future__ import annotations

import math

import pytest
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris, separation_arcsec

from sglseti.ephemeris import AstropyEphemeris, Ephemeris
from sglseti.errors import EphemerisCoverageError, EphemerisError
from sglseti.geometry import (
    SOLAR_FOCAL_MIN_AU,
    GeometryModel,
    Tusay2022Eq57V1,
    altaz_apparent,
    cirs_apparent,
    compute_relay_solution,
    observer_barycentric_au,
    solar_focal_min_au,
)
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    Observer,
    Role,
    Target,
    Validity,
)

MODEL = Tusay2022Eq57V1()
T_O = Time("2021-11-06T00:00:00", scale="utc")
EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))


def make_target(
    *,
    radial_velocity_km_s: float | None = 0.0,
    flags: tuple[str, ...] = (),
    d_au: float = 200_000.0,
    reference_epoch_jyear: float = 2000.0,
) -> Target:
    return Target(
        target_id="unit-test",
        display_name="Unit Test Star",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=100.0,
            pm_dec_mas_per_yr=-50.0,
            reference_epoch_jyear=reference_epoch_jyear,
            reference_epoch_scale="tdb",
            source="unit test values",
            distance_pc=d_au / AU_PER_PC,
            radial_velocity_km_s=radial_velocity_km_s,
        ),
        flags=flags,
    )


def test_protocol_conformance() -> None:
    assert isinstance(MODEL, GeometryModel)
    assert isinstance(EPHEMERIS, Ephemeris)
    assert isinstance(AstropyEphemeris(), Ephemeris)
    assert MODEL.model_id == "tusay2022_eq5_7_v1"
    assert MODEL.model_version == "1.1.0"


def test_direction_matches_direct_astropy_propagation() -> None:
    from astropy import units as u
    from astropy.coordinates import Distance, SkyCoord

    target = make_target()
    solution = MODEL.target_direction(target, T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)
    direct = SkyCoord(
        ra=10.0 * u.deg,
        dec=20.0 * u.deg,
        distance=Distance((200_000.0 / AU_PER_PC) * u.pc),
        pm_ra_cosdec=100.0 * u.mas / u.yr,
        pm_dec=-50.0 * u.mas / u.yr,
        radial_velocity=0.0 * u.km / u.s,
        obstime=Time(2000.0, format="jyear", scale="tdb"),
        frame="icrs",
    ).apply_space_motion(new_obstime=T_O.tdb)
    assert (
        separation_arcsec(
            solution.target_direction_icrs_ra_deg,
            solution.target_direction_icrs_dec_deg,
            float(direct.ra.deg),
            float(direct.dec.deg),
        )
        < 1e-9
    )


def test_z_beyond_search_prior_is_degraded_not_invalid() -> None:
    # d = 200000 au, so z > 20000 au exceeds the paper's z < d/10 search
    # prior. The equations remain evaluable: degraded with a distinct code,
    # never invalid (review finding 6).
    solution = MODEL.target_direction(make_target(), T_O, 25_000.0, Role.RX, EPHEMERIS)
    assert solution.validity is Validity.DEGRADED
    assert "outside_search_prior" in solution.warnings


def test_below_finite_source_focal_threshold_degrades() -> None:
    solution = MODEL.target_direction(make_target(), T_O, 500.0, Role.ANTIPODE, EPHEMERIS)
    assert "below_solar_focal_minimum" in solution.warnings
    assert solution.validity is Validity.DEGRADED  # review finding 4
    assert 500.0 < SOLAR_FOCAL_MIN_AU


def test_finite_source_focal_threshold_exceeds_infinite_source_constant() -> None:
    # z_min = f_inf d / (d - f_inf) > f_inf for every finite d; a sample
    # between the two thresholds lenses light from infinity but not from
    # this target.
    d_au = 200_000.0
    threshold = solar_focal_min_au(d_au)
    assert threshold > SOLAR_FOCAL_MIN_AU
    assert threshold == pytest.approx(
        SOLAR_FOCAL_MIN_AU * d_au / (d_au - SOLAR_FOCAL_MIN_AU)
    )
    between = (SOLAR_FOCAL_MIN_AU + threshold) / 2.0
    solution = MODEL.target_direction(make_target(), T_O, between, Role.ANTIPODE, EPHEMERIS)
    assert "below_solar_focal_minimum" in solution.warnings
    assert solution.validity is Validity.DEGRADED
    # A source at or inside f_inf can never reach focus.
    assert solar_focal_min_au(SOLAR_FOCAL_MIN_AU) == math.inf


def test_missing_radial_velocity_degrades_explicitly() -> None:
    target = make_target(
        radial_velocity_km_s=None, flags=("missing_radial_velocity",)
    )
    solution = MODEL.target_direction(target, T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)
    assert solution.validity is Validity.DEGRADED
    assert "missing_radial_velocity" in solution.warnings


@pytest.mark.filterwarnings("ignore:ERFA function.*dubious year")
def test_long_propagation_span_degrades() -> None:
    target = make_target(reference_epoch_jyear=1900.0)
    solution = MODEL.target_direction(target, T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)
    assert "long_propagation_span" in solution.warnings
    assert solution.validity is Validity.DEGRADED


def test_epoch_semantics_and_flags_are_fixed() -> None:
    solution = MODEL.target_direction(make_target(), T_O, 1000.0, Role.RX, EPHEMERIS)
    assert solution.catalog_epoch_semantics == "ssb_light_arrival_time"
    assert solution.rho_equals_z_assumed
    assert solution.constant_target_distance_assumed
    assert solution.linear_stellar_motion_assumed
    assert solution.solar_motion_neglected
    # rho = z: the observer-relay light time equals the Sun-relay light time.
    assert (
        solution.observer_relay_light_time_days_approx
        == solution.sun_relay_light_time_days
    )


def test_observer_barycentric_earth_center_equals_ephemeris_earth() -> None:
    import numpy as np

    vector = observer_barycentric_au(Observer.earth_center(), T_O, EPHEMERIS)
    assert np.allclose(vector, EPHEMERIS.earth_barycentric_au(T_O))


def test_observer_barycentric_site_offset_is_geocentric_radius() -> None:
    import numpy as np

    site = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)
    earth = EPHEMERIS.earth_barycentric_au(T_O)
    vector = observer_barycentric_au(site, T_O, EPHEMERIS)
    offset_km = float(np.linalg.norm(vector - earth)) * 149_597_870.7
    assert 6350.0 < offset_km < 6390.0  # geocentric radius at latitude 38.4


def test_earth_center_vs_topocentric_parallax() -> None:
    ephemeris = AstropyEphemeris()
    target = make_target()
    site = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)
    common = dict(
        target=target,
        observation_time=T_O,
        z_au=550.0,
        role=Role.ANTIPODE,
        ephemeris=ephemeris,
        model=MODEL,
    )
    geocentric = compute_relay_solution(observer=Observer.earth_center(), **common)
    topocentric = compute_relay_solution(observer=site, **common)
    parallax_arcsec = separation_arcsec(
        geocentric.los_icrs_ra_deg,
        geocentric.los_icrs_dec_deg,
        topocentric.los_icrs_ra_deg,
        topocentric.los_icrs_dec_deg,
    )
    # Geocentric radius (~4.25e-5 au) over 550 au: up to ~16 mas.
    assert 0.001 < parallax_arcsec < 0.020


def test_ephemeris_coverage_error_propagates() -> None:
    limited = FakeEphemeris(
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), coverage_jd=(2400000.0, 2450000.0)
    )
    with pytest.raises(EphemerisCoverageError, match="outside fake coverage"):
        compute_relay_solution(
            target=make_target(),
            observation_time=T_O,
            z_au=1000.0,
            role=Role.ANTIPODE,
            observer=Observer.earth_center(),
            ephemeris=limited,
            model=MODEL,
        )


def test_jpl_file_adapter_missing_kernel() -> None:
    with pytest.raises(EphemerisError, match="not found"):
        AstropyEphemeris(
            EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path="/nonexistent.bsp")
        )


def test_no_global_iers_mutation() -> None:
    from astropy.utils import iers

    before = iers.conf.auto_download
    compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=1000.0,
        role=Role.RX,
        observer=Observer.earth_center(),
        ephemeris=AstropyEphemeris(),
        model=MODEL,
    )
    assert iers.conf.auto_download == before


def test_solution_metadata_is_explicit() -> None:
    solution = compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=1000.0,
        role=Role.RX,
        observer=Observer.earth_center(),
        ephemeris=EPHEMERIS,
        model=MODEL,
    )
    assert solution.frame == "icrs"
    assert solution.correction == "geometric"
    assert solution.observer.observer_id == "earth-center"
    assert solution.ephemeris_id == "fake_fixture_ephemeris"
    assert solution.direction.model_id == "tusay2022_eq5_7_v1"
    assert solution.observation_time is T_O


def test_apparent_cirs_consistent_with_geometric_los() -> None:
    """Validates the finite-distance apparent construction.

    The relay's topocentric CIRS direction and the CIRS direction of a
    zero-parallax source placed at the geometric line of sight share the
    same aberration and frame rotation; they may differ only by how the
    transform handles the finite distance (sub-arcsecond). A gross error in
    the barycentric construction (e.g. re-applied parallax) would show up at
    the relay-parallax scale of arcminutes to degrees.
    """
    from astropy import units as u
    from astropy.coordinates import CIRS, SkyCoord

    site = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)
    solution = compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=550.0,
        role=Role.ANTIPODE,
        observer=site,
        ephemeris=AstropyEphemeris(),
        model=MODEL,
    )
    relay_cirs = cirs_apparent(solution)
    star_at_los = SkyCoord(
        ra=solution.los_icrs_ra_deg * u.deg,
        dec=solution.los_icrs_dec_deg * u.deg,
        frame="icrs",
    )
    from sglseti.ephemeris import offline_resources

    with offline_resources():
        star_cirs = star_at_los.transform_to(CIRS(obstime=T_O))
    assert (
        separation_arcsec(
            relay_cirs[0],
            relay_cirs[1],
            float(star_cirs.ra.deg),
            float(star_cirs.dec.deg),
        )
        < 0.5
    )
    # And CIRS differs from geometric ICRS by the expected precession-scale
    # rotation (not zero, not wild).
    shift = separation_arcsec(
        relay_cirs[0], relay_cirs[1], solution.los_icrs_ra_deg, solution.los_icrs_dec_deg
    )
    assert 60.0 < shift < 3600.0  # ~arcminutes for a 2021 epoch


def test_altaz_requires_site_and_is_finite() -> None:
    site = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)
    solution = compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=550.0,
        role=Role.ANTIPODE,
        observer=site,
        ephemeris=AstropyEphemeris(),
        model=MODEL,
    )
    alt, az = altaz_apparent(solution)
    assert -90.0 <= alt <= 90.0
    assert 0.0 <= az < 360.0

    geocentric = compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=550.0,
        role=Role.ANTIPODE,
        observer=Observer.earth_center(),
        ephemeris=AstropyEphemeris(),
        model=MODEL,
    )
    with pytest.raises(ValueError, match="site observer"):
        altaz_apparent(geocentric)


def test_invalid_relay_distance_rejected() -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        MODEL.target_direction(make_target(), T_O, -5.0, Role.RX, EPHEMERIS)


def test_geometry_module_has_no_io() -> None:
    """Exit criterion: no file writes, CLI calls, or planning in geometry."""
    import inspect

    import sglseti.geometry as geometry

    imported_modules = {
        value.__name__ for value in vars(geometry).values() if inspect.ismodule(value)
    }
    assert not {"argparse", "csv", "yaml", "pathlib", "json"} & imported_modules
    source = inspect.getsource(geometry)
    assert "open(" not in source
