"""Geometry regression against the Phase 0 reviewed reference fixtures.

Every expected value here was derived independently of both the prototype
and the engine (see tests/data/reference/README.md); the engine must
reproduce them through its own astropy/ERFA code path within each fixture's
stated tolerance.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from astropy.time import Time
from support import (
    AU_PER_PC,
    EXAMPLES_DIR,
    FakeEphemeris,
    load_reference_fixture,
    separation_arcsec,
)

from sglseti.ephemeris import AstropyEphemeris
from sglseti.geometry import (
    C_AU_PER_DAY,
    RelaySolution,
    Tusay2022Eq57V1,
    compute_relay_solution,
    motion_rates,
)
from sglseti.models import (
    AstrometricState,
    DirectionSolution,
    EndpointKind,
    Observer,
    Role,
    Target,
    Validity,
)
from sglseti.targets import load_target_registry

MODEL = Tusay2022Eq57V1()


def synthetic_target(
    *,
    ra_deg: float,
    dec_deg: float,
    d_au: float,
    pm_ra_cosdec_mas_per_yr: float,
    reference_epoch_jd_tdb: float,
) -> Target:
    return Target(
        target_id="synthetic",
        display_name="Synthetic",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            pm_ra_cosdec_mas_per_yr=pm_ra_cosdec_mas_per_yr,
            pm_dec_mas_per_yr=0.0,
            reference_epoch_jyear=2000.0 + (reference_epoch_jd_tdb - 2451545.0) / 365.25,
            reference_epoch_scale="tdb",
            source="synthetic fixture (tests/data/reference)",
            distance_pc=d_au / AU_PER_PC,
            radial_velocity_km_s=0.0,
        ),
    )


def tdb(jd: float) -> Time:
    return Time(jd, format="jd", scale="tdb")


def epoch_diff_days(engine_epoch: Time, fixture_jd: float) -> float:
    return abs(float((engine_epoch - tdb(fixture_jd)).jd))


def direction_sep_arcsec(direction: DirectionSolution, ra: float, dec: float) -> float:
    return separation_arcsec(
        direction.target_direction_icrs_ra_deg,
        direction.target_direction_icrs_dec_deg,
        ra,
        dec,
    )


def los_sep_arcsec(solution: RelaySolution, ra: float, dec: float) -> float:
    return separation_arcsec(solution.los_icrs_ra_deg, solution.los_icrs_dec_deg, ra, dec)


@pytest.fixture(scope="module")
def static_fixture() -> dict[str, Any]:
    return load_reference_fixture("static_synthetic.yaml")


@pytest.fixture(scope="module")
def cv_fixture() -> dict[str, Any]:
    return load_reference_fixture("constant_velocity_synthetic.yaml")


def solve_static(fixture: dict[str, Any], role: Role) -> RelaySolution:
    inputs = fixture["inputs"]
    target = synthetic_target(
        ra_deg=45.0,
        dec_deg=math.degrees(math.asin(1.0 / math.sqrt(3.0))),
        d_au=inputs["target"]["d_au"],
        pm_ra_cosdec_mas_per_yr=0.0,
        reference_epoch_jd_tdb=inputs["t_o_days"],
    )
    return compute_relay_solution(
        target=target,
        observation_time=tdb(inputs["t_o_days"]),
        z_au=inputs["z_au"],
        role=role,
        observer=Observer.earth_center(),
        ephemeris=FakeEphemeris(
            tuple(inputs["sun_barycentric_au"]), tuple(inputs["observer_barycentric_au"])
        ),
        model=MODEL,
    )


def solve_cv(fixture: dict[str, Any], role: Role) -> RelaySolution:
    inputs = fixture["inputs"]
    catalog = inputs["equivalent_catalog_parameters"]
    target = synthetic_target(
        ra_deg=catalog["ra_deg"],
        dec_deg=catalog["dec_deg"],
        d_au=catalog["d0_au"],
        pm_ra_cosdec_mas_per_yr=catalog["pm_ra_cosdec_arcsec_per_yr"] * 1000.0,
        reference_epoch_jd_tdb=catalog["reference_arrival_epoch_u0_days"],
    )
    return compute_relay_solution(
        target=target,
        observation_time=tdb(inputs["t_o_days"]),
        z_au=inputs["z_au"],
        role=role,
        observer=Observer.earth_center(),
        ephemeris=FakeEphemeris(
            tuple(inputs["sun_barycentric_au"]), tuple(inputs["observer_barycentric_au"])
        ),
        model=MODEL,
    )


class TestStaticSynthetic:
    """Zero-motion limit: all roles share one direction (static fixture)."""

    @pytest.mark.parametrize("role", list(Role))
    def test_direction_and_los_match_fixture(
        self, static_fixture: dict[str, Any], role: Role
    ) -> None:
        expected = static_fixture["expected"]
        tol = static_fixture["tolerance"]["direction_arcsec"]
        solution = solve_static(static_fixture, role)
        assert (
            direction_sep_arcsec(
                solution.direction,
                expected["target_dir_ra_deg"],
                expected["target_dir_dec_deg"],
            )
            < tol
        )
        assert los_sep_arcsec(solution, expected["los_ra_deg"], expected["los_dec_deg"]) < tol
        assert abs(solution.rho_au - expected["rho_au"]) < 1e-6
        assert solution.direction.validity is Validity.VALID

    def test_role_epochs(self, static_fixture: dict[str, Any]) -> None:
        expected = static_fixture["expected"]["role_epochs_days"]
        tol = static_fixture["tolerance"]["epoch_days_abs"]
        for role in Role:
            solution = solve_static(static_fixture, role)
            assert (
                epoch_diff_days(solution.direction.catalog_direction_epoch, expected[role.value])
                < tol
            )

    def test_roles_share_one_direction(self, static_fixture: dict[str, Any]) -> None:
        solutions = [solve_static(static_fixture, role) for role in Role]
        reference = solutions[0].direction
        for solution in solutions[1:]:
            assert (
                direction_sep_arcsec(
                    solution.direction,
                    reference.target_direction_icrs_ra_deg,
                    reference.target_direction_icrs_dec_deg,
                )
                < 1e-6
            )


class TestConstantVelocitySynthetic:
    """Catalog-arrival vs physical-event equivalence and Rx/Tx distinction.

    The frozen directions were computed by physically propagating the star
    and solving the emission-time equation; the engine reproduces them here
    through ERFA catalog propagation — the cross-convention agreement that
    is the point of this fixture.
    """

    @pytest.mark.parametrize("role", list(Role))
    def test_directions_match_physical_oracle(self, cv_fixture: dict[str, Any], role: Role) -> None:
        expected = cv_fixture["expected"][role.value]
        tol = cv_fixture["tolerance"]["direction_arcsec"]
        solution = solve_cv(cv_fixture, role)
        assert (
            direction_sep_arcsec(
                solution.direction,
                expected["target_dir_ra_deg"],
                expected["target_dir_dec_deg"],
            )
            < tol
        )
        assert los_sep_arcsec(solution, expected["los_ra_deg"], expected["los_dec_deg"]) < tol

    @pytest.mark.parametrize("role", list(Role))
    def test_catalog_and_physical_epochs(self, cv_fixture: dict[str, Any], role: Role) -> None:
        expected = cv_fixture["expected"][role.value]
        solution = solve_cv(cv_fixture, role)
        # tx's catalog epoch depends on the declared d; ERFA's light-time
        # solution and the oracle differ at the milli-AU level (~1 s of
        # epoch, sub-microarcsecond of direction), so tx gets a wider epoch
        # tolerance. antipode/rx epochs depend only on t_o and z: exact.
        tol = 1e-4 if role is Role.TX else cv_fixture["tolerance"]["epoch_days_abs"]
        assert (
            epoch_diff_days(
                solution.direction.catalog_direction_epoch,
                expected["catalog_epoch_u_days"],
            )
            < tol
        )
        # The physical-event diagnostic sits one target light time from the
        # catalog epoch (never fed back into propagation).
        assert (
            epoch_diff_days(
                solution.direction.target_event_epoch_approx,
                expected["physical_event_epoch_days"],
            )
            < 1e-4
        )

    def test_declared_distance(self, cv_fixture: dict[str, Any]) -> None:
        # ERFA's propagated distance and the oracle's |r(t_e)| agree at the
        # milli-AU level; the resulting direction effect is far inside the
        # 1 mas tolerance.
        solution = solve_cv(cv_fixture, Role.ANTIPODE)
        d_days = solution.direction.target_light_time_days
        assert abs(d_days * C_AU_PER_DAY - cv_fixture["derived"]["d_au_declared"]) < 0.01

    def test_rx_tx_distinction(self, cv_fixture: dict[str, Any]) -> None:
        antipode = solve_cv(cv_fixture, Role.ANTIPODE).direction
        rx = solve_cv(cv_fixture, Role.RX).direction
        tx = solve_cv(cv_fixture, Role.TX).direction
        rx_offset = direction_sep_arcsec(
            rx,
            antipode.target_direction_icrs_ra_deg,
            antipode.target_direction_icrs_dec_deg,
        )
        tx_offset = direction_sep_arcsec(
            tx,
            antipode.target_direction_icrs_ra_deg,
            antipode.target_direction_icrs_dec_deg,
        )
        sanity = cv_fixture["sanity"]
        assert math.isclose(
            rx_offset, abs(sanity["rx_minus_antipode_target_dir_arcsec"]), rel_tol=0.01
        )
        assert math.isclose(tx_offset, sanity["tx_minus_antipode_target_dir_arcsec"], rel_tol=0.01)


class TestDoubleRetardedNegative:
    """The double-retarded Rx construction must be DETECTED, never matched."""

    def test_engine_rx_is_far_from_wrong_construction(self, cv_fixture: dict[str, Any]) -> None:
        negative = load_reference_fixture("double_retarded_negative.yaml")
        solution = solve_cv(cv_fixture, Role.RX)
        wrong = negative["wrong_construction"]
        offset_from_wrong = direction_sep_arcsec(
            solution.direction, wrong["target_dir_ra_deg"], wrong["target_dir_dec_deg"]
        )
        detection = negative["expected_detection"]
        assert offset_from_wrong > detection["min_detectable_offset_arcsec"]
        assert (
            abs(offset_from_wrong - detection["offset_from_correct_rx_arcsec"])
            < 2 * negative["tolerance"]["offset_arcsec_abs"]
        )
        # And the wrong catalog epoch is exactly the physical-event
        # diagnostic — present as output, forbidden as propagation input.
        assert (
            epoch_diff_days(
                solution.direction.target_event_epoch_approx,
                wrong["catalog_epoch_u_days"],
            )
            < 1e-4
        )


@pytest.fixture(scope="module")
def barnard_fixture() -> dict[str, Any]:
    return load_reference_fixture("barnard_scale_check.yaml")


@pytest.fixture(scope="module")
def barnard() -> Target:
    return load_target_registry(EXAMPLES_DIR / "targets.yaml")["barnard"]


def barnard_direction(target: Target, role: Role, z_au: float) -> DirectionSolution:
    ephemeris = FakeEphemeris((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    return MODEL.target_direction(
        target, Time("2021-11-06T00:00:00", scale="utc"), z_au, role, ephemeris
    )


class TestBarnardScaleCheck:
    """High-proper-motion Rx/Tx offset scale and sign."""

    def test_rx_offsets_scale(self, barnard_fixture: dict[str, Any], barnard: Target) -> None:
        tol_fraction = barnard_fixture["tolerance"]["offset_fraction"]
        antipode = barnard_direction(barnard, Role.ANTIPODE, 550.0)
        for z_au, key in ((550.0, "z_550_au"), (2500.0, "z_2500_au")):
            rx = barnard_direction(barnard, Role.RX, z_au)
            offset = direction_sep_arcsec(
                rx,
                antipode.target_direction_icrs_ra_deg,
                antipode.target_direction_icrs_dec_deg,
            )
            expected = barnard_fixture["expected"]["rx_offset_from_antipode_arcsec"][key]
            assert abs(offset - expected) < tol_fraction * expected

    def test_tx_offset_scale_and_signs(
        self, barnard_fixture: dict[str, Any], barnard: Target
    ) -> None:
        tol_fraction = barnard_fixture["tolerance"]["offset_fraction"]
        antipode = barnard_direction(barnard, Role.ANTIPODE, 550.0)
        tx = barnard_direction(barnard, Role.TX, 550.0)
        rx = barnard_direction(barnard, Role.RX, 550.0)
        offset = direction_sep_arcsec(
            tx,
            antipode.target_direction_icrs_ra_deg,
            antipode.target_direction_icrs_dec_deg,
        )
        expected = barnard_fixture["expected"]["tx_offset_from_antipode_arcsec"]
        assert abs(offset - expected) < tol_fraction * expected
        # Signs: mu_dec is strongly positive, so the later-epoch (tx)
        # direction sits north of antipode and the earlier-epoch (rx) south.
        assert tx.target_direction_icrs_dec_deg > antipode.target_direction_icrs_dec_deg
        assert rx.target_direction_icrs_dec_deg < antipode.target_direction_icrs_dec_deg


@pytest.fixture(scope="module")
def acen_fixture() -> dict[str, Any]:
    return load_reference_fixture("alpha_cen_2021-11-06.yaml")


@pytest.fixture(scope="module")
def acen_context(acen_fixture: dict[str, Any]) -> tuple:
    astrometry = acen_fixture["inputs"]["astrometry"]
    target = Target(
        target_id="alpha-cen-a",
        display_name="Alpha Centauri A",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=astrometry["ra_deg"],
            dec_deg=astrometry["dec_deg"],
            parallax_mas=astrometry["parallax_mas"],
            pm_ra_cosdec_mas_per_yr=astrometry["pm_ra_cosdec_mas_per_yr"],
            pm_dec_mas_per_yr=astrometry["pm_dec_mas_per_yr"],
            radial_velocity_km_s=astrometry["radial_velocity_km_s"],
            reference_epoch_jyear=astrometry["reference_epoch_jyear"],
            reference_epoch_scale=astrometry["reference_epoch_scale"],
            source="SIMBAD display captured 2026-08-17 (fixture)",
        ),
    )
    observer_data = acen_fixture["inputs"]["observer"]
    observer = Observer.from_geodetic(
        "gbt",
        observer_data["longitude_deg"],
        observer_data["latitude_deg"],
        observer_data["height_m"],
    )
    t_o = Time(acen_fixture["inputs"]["t_o_utc"], scale="utc")
    return target, observer, t_o, AstropyEphemeris()


class TestAlphaCenPublishedEpoch:
    """Published-search anchor: reproduce the eq. 5-7 reference script."""

    @pytest.mark.parametrize("z_au", [550.0, 1000.0, 2500.0])
    @pytest.mark.parametrize("role", list(Role))
    def test_reproduces_reference_script(
        self, acen_fixture: dict[str, Any], acen_context: tuple, role: Role, z_au: float
    ) -> None:
        target, observer, t_o, ephemeris = acen_context
        expected = acen_fixture["expected"][f"{role.value}_z{z_au:g}"]
        tol = acen_fixture["tolerance"]["reproducibility_arcsec"]
        solution = compute_relay_solution(
            target=target,
            observation_time=t_o,
            z_au=z_au,
            role=role,
            observer=observer,
            ephemeris=ephemeris,
            model=MODEL,
        )
        assert los_sep_arcsec(solution, expected["los_ra_deg"], expected["los_dec_deg"]) < tol
        if "target_dir_ra_deg" in expected:
            assert (
                direction_sep_arcsec(
                    solution.direction,
                    expected["target_dir_ra_deg"],
                    expected["target_dir_dec_deg"],
                )
                < tol
            )
        if role is Role.TX:
            # The engine declares d at the antipode arrival epoch; the
            # reference script used the catalog-epoch (J2000) distance. The
            # -15.25 km/s radial velocity is ~3.2 AU/yr, so over the ~21.9 yr
            # J2000 -> 2021 span the two conventions differ by ~70 AU
            # (~0.8 d of tx epoch, ~8 mas of direction — inside the 2 arcsec
            # tolerance, checked above).
            d_engine = solution.direction.target_light_time_days * C_AU_PER_DAY
            assert abs(d_engine - acen_fixture["derived"]["d_au"]) < 100.0
            # Self-consistency of the tx epoch with the declared d.
            gap = float(
                (
                    solution.direction.catalog_direction_epoch
                    - solution.direction.observation_epoch
                ).jd
            )
            assert abs(gap - 2.0 * solution.direction.target_light_time_days) < 1e-9
        else:
            assert (
                epoch_diff_days(
                    solution.direction.catalog_direction_epoch,
                    expected["catalog_epoch_tdb_jd"],
                )
                < 1e-6
            )
        assert solution.direction.validity is Validity.VALID
        assert solution.ephemeris_id == "astropy_builtin"

    def test_antipodal_region_sanity(
        self, acen_fixture: dict[str, Any], acen_context: tuple
    ) -> None:
        target, observer, t_o, ephemeris = acen_context
        solution = compute_relay_solution(
            target=target,
            observation_time=t_o,
            z_au=550.0,
            role=Role.ANTIPODE,
            observer=observer,
            ephemeris=ephemeris,
            model=MODEL,
        )
        # Paper pointing region (their Figure 3): ~RA 02h39m, Dec +60.9 deg.
        tol_deg = acen_fixture["tolerance"]["publication_consistency_arcmin"] / 60.0
        assert abs(solution.los_icrs_ra_deg - 39.85) < tol_deg * 2.0
        assert abs(solution.los_icrs_dec_deg - 60.90) < tol_deg

    def test_rho_matches_reference(self, acen_fixture: dict[str, Any], acen_context: tuple) -> None:
        target, observer, t_o, ephemeris = acen_context
        solution = compute_relay_solution(
            target=target,
            observation_time=t_o,
            z_au=550.0,
            role=Role.ANTIPODE,
            observer=observer,
            ephemeris=ephemeris,
            model=MODEL,
        )
        expected_rho = acen_fixture["expected"]["antipode_z550"]["rho_au"]
        assert abs(solution.rho_au - expected_rho) < 1e-3

    def test_rate_convergence(self, acen_context: tuple) -> None:
        target, observer, t_o, ephemeris = acen_context
        coarse = motion_rates(
            target=target,
            observation_time=t_o,
            z_au=550.0,
            role=Role.ANTIPODE,
            observer=observer,
            ephemeris=ephemeris,
            model=MODEL,
            step_s=60.0,
        )
        fine = motion_rates(
            target=target,
            observation_time=t_o,
            z_au=550.0,
            role=Role.ANTIPODE,
            observer=observer,
            ephemeris=ephemeris,
            model=MODEL,
            step_s=15.0,
        )
        magnitude = math.hypot(coarse.rate_ra_cosdec_arcsec_per_hr, coarse.rate_dec_arcsec_per_hr)
        # Relay parallax motion from Earth's orbit: ~0.05-1 arcsec/hr scale.
        assert 0.01 < magnitude < 5.0
        assert abs(coarse.rate_ra_cosdec_arcsec_per_hr - fine.rate_ra_cosdec_arcsec_per_hr) < 0.01
        assert abs(coarse.rate_dec_arcsec_per_hr - fine.rate_dec_arcsec_per_hr) < 0.01
        assert coarse.step_s == 60.0 and fine.step_s == 15.0
