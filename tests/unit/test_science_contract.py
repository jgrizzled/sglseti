"""Phase 0 science-contract tests.

Guards the frozen ``DirectionSolution`` field set and re-derives every
reviewed reference fixture's arithmetic from constants, independently of the
generator scripts, so the frozen values cannot drift silently. Geometry
regression against these fixtures lands in Phase 4.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import yaml

from sglseti.models import SUPPORTED_MODEL_IDS, DirectionSolution

REFERENCE = Path(__file__).resolve().parents[2] / "tests" / "data" / "reference"

C_AU_PER_DAY = 299_792_458 * 86_400 / 149_597_870_700
AU_PER_PC = 648_000 / math.pi
ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi


def load(name: str) -> dict[str, Any]:
    with (REFERENCE / name).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


# Frozen in docs/science/geometry_models.md section 4. Changing this list is
# a science-contract change and requires an ADR update, not just a code edit.
FROZEN_DIRECTION_SOLUTION_FIELDS = (
    "model_id",
    "model_version",
    "role",
    "observation_epoch",
    "catalog_direction_epoch",
    "relay_event_epoch_approx",
    "solar_lens_epoch_approx",
    "target_event_epoch_approx",
    "target_event_kind",
    "target_light_time_days",
    "sun_relay_light_time_days",
    "observer_relay_light_time_days_approx",
    "target_direction_icrs_ra_deg",
    "target_direction_icrs_dec_deg",
    "validity",
    "warnings",
    "catalog_epoch_semantics",
    "rho_equals_z_assumed",
    "constant_target_distance_assumed",
    "linear_stellar_motion_assumed",
    "solar_motion_neglected",
)


def test_direction_solution_fields_frozen() -> None:
    names = tuple(field.name for field in dataclasses.fields(DirectionSolution))
    assert names == FROZEN_DIRECTION_SOLUTION_FIELDS


def test_v1_model_registry() -> None:
    assert SUPPORTED_MODEL_IDS == frozenset({"tusay2022_eq5_7_v1"})


def test_solar_focal_distance_rederivation() -> None:
    fixture = load("solar_focal_distance.yaml")
    constants = fixture["constants"]
    r_g = 2.0 * constants["GM_sun_m3_s2"] / constants["c_m_s"] ** 2
    z_min_m = constants["R_sun_m"] ** 2 / (2.0 * r_g)
    z_min_au = z_min_m / constants["au_m"]
    expected = fixture["expected"]
    assert math.isclose(r_g, expected["r_g_m"], rel_tol=1e-12)
    assert abs(z_min_au - expected["z_min_au"]) < fixture["tolerance"]["z_min_au_abs"]
    # PRD sanity: approximately 547.8 AU.
    assert 547.0 < z_min_au < 548.5


def test_role_epoch_offsets_rederivation() -> None:
    fixture = load("role_epoch_offsets.yaml")
    assert math.isclose(fixture["c_au_per_day"], C_AU_PER_DAY, rel_tol=1e-12)
    tol = fixture["tolerance"]["days_abs"]
    for entry in fixture["rx_offsets"]:
        assert abs(2.0 * entry["z_au"] / C_AU_PER_DAY - entry["two_z_over_c_days"]) < tol
    for entry in fixture["tx_offsets"]:
        if "parallax_mas" in entry:
            d_au = 1000.0 / entry["parallax_mas"] * AU_PER_PC
            assert math.isclose(d_au, entry["d_au"], rel_tol=1e-9)
        else:
            d_au = entry["d_au"]
        assert abs(2.0 * d_au / C_AU_PER_DAY - entry["two_d_over_c_days"]) < tol
        if "two_d_over_c_years" in entry:
            assert math.isclose(
                entry["two_d_over_c_days"] / 365.25,
                entry["two_d_over_c_years"],
                rel_tol=1e-9,
            )


def test_static_fixture_epoch_arithmetic_and_role_identity() -> None:
    fixture = load("static_synthetic.yaml")
    t_o = fixture["inputs"]["t_o_days"]
    z = fixture["inputs"]["z_au"]
    d = fixture["inputs"]["target"]["d_au"]
    epochs = fixture["expected"]["role_epochs_days"]
    tol = fixture["tolerance"]["epoch_days_abs"]
    assert abs(epochs["antipode"] - t_o) < tol
    assert abs(epochs["rx"] - (t_o - 2.0 * z / C_AU_PER_DAY)) < tol
    assert abs(epochs["tx"] - (t_o + 2.0 * d / C_AU_PER_DAY)) < tol
    # Zero-motion limit: one direction for all roles is encoded as single
    # expected values; the direction differs from the LOS (relay parallax).
    expected = fixture["expected"]
    assert expected["target_dir_ra_deg"] != expected["los_ra_deg"]
    # rho consistency: |S - O - z a| expands to rho - z ~= +(O - S) . a_hat
    # to first order in |O - S| / z.
    sun = fixture["inputs"]["sun_barycentric_au"]
    obs = fixture["inputs"]["observer_barycentric_au"]
    ra = math.radians(expected["target_dir_ra_deg"])
    dec = math.radians(expected["target_dir_dec_deg"])
    a_hat = (
        math.cos(dec) * math.cos(ra),
        math.cos(dec) * math.sin(ra),
        math.sin(dec),
    )
    rel = [o - s for o, s in zip(obs, sun, strict=True)]
    first_order = sum(r * a for r, a in zip(rel, a_hat, strict=True))
    assert abs(expected["rho_minus_z_au"] - first_order) < 1e-3


def test_constant_velocity_fixture_offsets() -> None:
    fixture = load("constant_velocity_synthetic.yaml")
    mu_arcsec_per_day = (
        fixture["inputs"]["equivalent_catalog_parameters"]["pm_ra_cosdec_arcsec_per_yr"]
        / 365.25
    )
    expected = fixture["expected"]
    tol = 0.005  # arcsec, on first-order comparisons of frozen values

    def ra_arcsec(role: str) -> float:
        ra = expected[role]["target_dir_ra_deg"]
        return ((ra + 180.0) % 360.0 - 180.0) * 3600.0  # unwrap around 0

    two_z_over_c = fixture["derived"]["two_z_over_c_days"]
    two_d_over_c = fixture["derived"]["two_d_over_c_days"]
    rx_offset = ra_arcsec("rx") - ra_arcsec("antipode")
    tx_offset = ra_arcsec("tx") - ra_arcsec("antipode")
    assert abs(rx_offset - (-mu_arcsec_per_day * two_z_over_c)) < tol
    assert abs(tx_offset - mu_arcsec_per_day * two_d_over_c) < tol
    # Epoch arithmetic.
    t_o = fixture["inputs"]["t_o_days"]
    tol_days = fixture["tolerance"]["epoch_days_abs"]
    assert abs(expected["rx"]["catalog_epoch_u_days"] - (t_o - two_z_over_c)) < tol_days
    assert abs(expected["tx"]["catalog_epoch_u_days"] - (t_o + two_d_over_c)) < tol_days
    # Physical event epoch = catalog epoch - d/c (to sub-second precision).
    d_over_c = fixture["derived"]["d_au_declared"] / C_AU_PER_DAY
    for role in ("antipode", "rx", "tx"):
        gap = (
            expected[role]["catalog_epoch_u_days"]
            - expected[role]["physical_event_epoch_days"]
        )
        assert abs(gap - d_over_c) < 1e-4


def test_double_retarded_negative_fixture() -> None:
    fixture = load("double_retarded_negative.yaml")
    base = load("constant_velocity_synthetic.yaml")
    mu_rad_per_day = (
        base["inputs"]["equivalent_catalog_parameters"]["pm_ra_cosdec_arcsec_per_yr"]
        / ARCSEC_PER_RAD
        / 365.25
    )
    d_over_c = base["derived"]["d_au_declared"] / C_AU_PER_DAY
    analytic = mu_rad_per_day * d_over_c * ARCSEC_PER_RAD
    detection = fixture["expected_detection"]
    assert math.isclose(detection["analytic_offset_arcsec"], analytic, rel_tol=1e-6)
    assert (
        abs(detection["offset_from_correct_rx_arcsec"] - analytic)
        < fixture["tolerance"]["offset_arcsec_abs"]
    )
    # The wrong construction must sit far outside the direction tolerance.
    assert (
        detection["offset_from_correct_rx_arcsec"]
        > detection["min_detectable_offset_arcsec"]
    )
    # Wrong epoch = correct rx epoch - d/c.
    u_rx = base["expected"]["rx"]["catalog_epoch_u_days"]
    assert abs(fixture["wrong_construction"]["catalog_epoch_u_days"] - (u_rx - d_over_c)) < 1e-4


def test_barnard_scale_check_rederivation() -> None:
    fixture = load("barnard_scale_check.yaml")
    inputs = fixture["inputs"]
    mu = math.hypot(inputs["pm_ra_cosdec_mas_per_yr"], inputs["pm_dec_mas_per_yr"])
    assert math.isclose(mu, fixture["derived"]["mu_total_mas_per_yr"], rel_tol=1e-9)
    d_au = 1000.0 / inputs["parallax_mas"] * AU_PER_PC
    two_d_over_c_years = 2.0 * d_au / C_AU_PER_DAY / 365.25
    assert math.isclose(
        two_d_over_c_years, fixture["derived"]["two_d_over_c_years"], rel_tol=1e-9
    )
    expected = fixture["expected"]
    for z_key, z_au in (("z_550_au", 550.0), ("z_2500_au", 2500.0)):
        first_order = mu / 1000.0 * (2.0 * z_au / C_AU_PER_DAY / 365.25)
        assert math.isclose(
            expected["rx_offset_from_antipode_arcsec"][z_key], first_order, rel_tol=1e-9
        )
    assert math.isclose(
        expected["tx_offset_from_antipode_arcsec"],
        mu / 1000.0 * two_d_over_c_years,
        rel_tol=1e-9,
    )


def test_alpha_cen_fixture_role_epochs() -> None:
    fixture = load("alpha_cen_2021-11-06.yaml")
    t_o = fixture["inputs"]["t_o_tdb_jd"]
    d_au = fixture["derived"]["d_au"]
    parallax = fixture["inputs"]["astrometry"]["parallax_mas"]
    assert math.isclose(d_au, 1000.0 / parallax * AU_PER_PC, rel_tol=1e-9)
    two_d_over_c = fixture["derived"]["two_d_over_c_days"]
    assert math.isclose(two_d_over_c, 2.0 * d_au / C_AU_PER_DAY, rel_tol=1e-12)
    expected = fixture["expected"]
    for z_au in (550.0, 1000.0, 2500.0):
        key = f"{z_au:g}"
        assert abs(expected[f"antipode_z{key}"]["catalog_epoch_tdb_jd"] - t_o) < 1e-6
        assert (
            abs(
                expected[f"rx_z{key}"]["catalog_epoch_tdb_jd"]
                - (t_o - 2.0 * z_au / C_AU_PER_DAY)
            )
            < 1e-6
        )
        assert (
            abs(expected[f"tx_z{key}"]["catalog_epoch_tdb_jd"] - (t_o + two_d_over_c))
            < 1e-6
        )
    # z=550 sits just above the solar focal minimum; validity bound z < d/10.
    assert 550.0 < d_au / 10.0
    # rho ~= z within ~1.1 au for a terrestrial observer.
    rho = expected["antipode_z550"]["rho_au"]
    assert abs(rho - 550.0) < 1.1


def test_all_fixtures_declare_tolerance_and_model() -> None:
    for name in (
        "role_epoch_offsets.yaml",
        "static_synthetic.yaml",
        "constant_velocity_synthetic.yaml",
        "double_retarded_negative.yaml",
        "barnard_scale_check.yaml",
        "alpha_cen_2021-11-06.yaml",
    ):
        fixture = load(name)
        assert fixture.get("model_id") == "tusay2022_eq5_7_v1", name
        assert "tolerance" in fixture, name
        assert "fixture_id" in fixture, name
