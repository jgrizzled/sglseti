#!/usr/bin/env python3
"""Independent first-principles generator for the synthetic geometry fixtures.

This script is a Phase 0 oracle: it derives the expected role epochs and
directions for the synthetic regression fixtures directly from flat-space
light propagation, WITHOUT astropy, ERFA, catalog-propagation conventions, or
any sgl-search-planner / sglseti code. Values frozen into the fixture YAML
files come from this script; the Phase 4 geometry engine must reproduce them
through the entirely separate astropy/ERFA code path.

Conventions (deliberately minimal):
- One uniform time coordinate in days (Julian-date-like numbering, "synthetic
  TDB"). No UTC, no leap seconds, no relativistic scales.
- Cartesian ICRS-like axes, origin at the SSB. Units: AU and days.
- The star moves linearly: r(t) = r0 + v * (t - t0).
- The catalog direction a(u), indexed by SSB light-arrival epoch u, is
  DEFINED physically: solve t_e = u - |r(t_e)|/c for the emission event, then
  a(u) = unit(r(t_e)). This is the Gaia arrival-time convention built from
  first principles rather than from ERFA.
- Role catalog epochs follow the reconciled tusay2022_eq5_7_v1 convention:
      antipode: u = t_o
      rx:       u = t_o - 2 z / c
      tx:       u = t_o + 2 d / c
- Relay locus (Tusay et al. 2022 eq. 5 with role-corrected direction):
      P = S(t_o) - z * a(u_role)
  and the observer line of sight is unit(P - O(t_o)).

Run:  python generate_synthetic_fixtures.py
"""

from __future__ import annotations

import json
import math

# Speed of light in AU/day from defining constants:
# c = 299792458 m/s, 1 au = 149597870700 m, 1 day = 86400 s.
C_AU_PER_DAY = 299_792_458 * 86_400 / 149_597_870_700

ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi

Vec = tuple[float, float, float]


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def norm(a: Vec) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def unit(a: Vec) -> Vec:
    n = norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def radec_deg(v: Vec) -> tuple[float, float]:
    u = unit(v)
    ra = math.degrees(math.atan2(u[1], u[0])) % 360.0
    dec = math.degrees(math.asin(u[2]))
    return ra, dec


def separation_arcsec(a: Vec, b: Vec) -> float:
    cosang = max(-1.0, min(1.0, dot(unit(a), unit(b))))
    return math.acos(cosang) * ARCSEC_PER_RAD


class LinearStar:
    """Physically moving star: r(t) = r0 + v (t - t0)."""

    def __init__(self, r0: Vec, v: Vec, t0: float) -> None:
        self.r0, self.v, self.t0 = r0, v, t0

    def physical_position(self, t: float) -> Vec:
        return add(self.r0, scale(self.v, t - self.t0))

    def emission_time_for_arrival(self, u: float) -> float:
        """Solve t_e = u - |r(t_e)|/c by fixed-point iteration (exact)."""
        t_e = u - norm(self.physical_position(u)) / C_AU_PER_DAY
        for _ in range(60):
            t_next = u - norm(self.physical_position(t_e)) / C_AU_PER_DAY
            if abs(t_next - t_e) < 1e-13:
                return t_next
            t_e = t_next
        raise RuntimeError("light-time iteration did not converge")

    def catalog_direction(self, u: float) -> Vec:
        """Arrival-indexed astrometric direction a(u), defined physically."""
        return unit(self.physical_position(self.emission_time_for_arrival(u)))


def line_of_sight(sun: Vec, observer: Vec, direction: Vec, z_au: float) -> tuple[Vec, Vec]:
    relay = sub(sun, scale(direction, z_au))
    return relay, unit(sub(relay, observer))


def fmt(x: float) -> float:
    return float(f"{x:.15g}")


def fixture_static() -> dict:
    t_o = 2459524.5  # synthetic uniform time, days
    d_au = 200_000.0
    n = unit((1.0, 1.0, 1.0))
    star = LinearStar(scale(n, d_au), (0.0, 0.0, 0.0), t_o)
    z_au = 1000.0
    sun = (0.004, -0.002, 0.001)
    observer = (0.5580, -0.7440, -0.3230)

    u_rx = t_o - 2.0 * z_au / C_AU_PER_DAY
    u_tx = t_o + 2.0 * d_au / C_AU_PER_DAY
    roles = {"antipode": t_o, "rx": u_rx, "tx": u_tx}
    out: dict = {
        "t_o_days": t_o,
        "d_au": d_au,
        "z_au": z_au,
        "sun_au": list(sun),
        "observer_au": list(observer),
        "two_z_over_c_days": fmt(2.0 * z_au / C_AU_PER_DAY),
        "two_d_over_c_days": fmt(2.0 * d_au / C_AU_PER_DAY),
        "roles": {},
    }
    for role, u in roles.items():
        a = star.catalog_direction(u)
        relay, los = line_of_sight(sun, observer, a, z_au)
        ra, dec = radec_deg(los)
        a_ra, a_dec = radec_deg(a)
        rho = norm(sub(relay, observer))
        out["roles"][role] = {
            "catalog_epoch_u_days": fmt(u),
            "target_dir_ra_deg": fmt(a_ra),
            "target_dir_dec_deg": fmt(a_dec),
            "los_ra_deg": fmt(ra),
            "los_dec_deg": fmt(dec),
            "rho_au": fmt(rho),
            "rho_minus_z_au": fmt(rho - z_au),
        }
    # All roles must share one direction for a static target.
    dirs = [
        (r["target_dir_ra_deg"], r["target_dir_dec_deg"]) for r in out["roles"].values()
    ]
    assert dirs.count(dirs[0]) == 3
    return out


def fixture_constant_velocity() -> dict:
    t0 = 2459000.0
    d0_au = 200_000.0
    n0 = (1.0, 0.0, 0.0)
    # Transverse velocity giving 10 arcsec/yr of proper motion at d0.
    mu_rad_per_day = 10.0 / ARCSEC_PER_RAD / 365.25
    v = (0.0, mu_rad_per_day * d0_au, 0.0)  # motion toward +y (east at ra=0,dec=0)
    star = LinearStar(scale(n0, d0_au), v, t0)

    t_o = 2459524.5
    z_au = 1000.0
    sun = (0.004, -0.002, 0.001)
    observer = (0.5580, -0.7440, -0.3230)

    # Reference arrival epoch chosen so a(u0) = n0 exactly (t_e = t0).
    u0 = t0 + d0_au / C_AU_PER_DAY

    # Declared d for the model: distance of the emission event seen at t_o.
    t_e_apparent = star.emission_time_for_arrival(t_o)
    d_au = norm(star.physical_position(t_e_apparent))

    u_rx = t_o - 2.0 * z_au / C_AU_PER_DAY
    u_tx = t_o + 2.0 * d_au / C_AU_PER_DAY

    out: dict = {
        "t0_days": t0,
        "d0_au": d0_au,
        "n0": list(n0),
        "v_au_per_day": [fmt(c) for c in v],
        "proper_motion_arcsec_per_yr": 10.0,
        "radial_velocity": 0.0,
        "u0_days": fmt(u0),
        "t_o_days": t_o,
        "z_au": z_au,
        "sun_au": list(sun),
        "observer_au": list(observer),
        "d_au_declared": fmt(d_au),
        "two_z_over_c_days": fmt(2.0 * z_au / C_AU_PER_DAY),
        "two_d_over_c_days": fmt(2.0 * d_au / C_AU_PER_DAY),
        "roles": {},
    }

    for role, u in (("antipode", t_o), ("rx", u_rx), ("tx", u_tx)):
        # Catalog-arrival formulation.
        a_catalog = star.catalog_direction(u)
        # Physical-event formulation: same photons, physical state at t_e(u).
        t_event = star.emission_time_for_arrival(u)
        a_physical = unit(star.physical_position(t_event))
        equivalence_arcsec = separation_arcsec(a_catalog, a_physical)
        assert equivalence_arcsec < 1e-9  # definitional here; real test is Phase 4
        relay, los = line_of_sight(sun, observer, a_catalog, z_au)
        ra, dec = radec_deg(los)
        a_ra, a_dec = radec_deg(a_catalog)
        out["roles"][role] = {
            "catalog_epoch_u_days": fmt(u),
            "physical_event_epoch_days": fmt(t_event),
            "target_dir_ra_deg": fmt(a_ra),
            "target_dir_dec_deg": fmt(a_dec),
            "los_ra_deg": fmt(ra),
            "los_dec_deg": fmt(dec),
        }

    # Deliberately double-retarded Rx: catalog direction wrongly evaluated at
    # the physical emission epoch u_rx - d/c instead of the arrival epoch u_rx.
    u_wrong = u_rx - d_au / C_AU_PER_DAY
    a_wrong = star.catalog_direction(u_wrong)
    a_correct = star.catalog_direction(u_rx)
    offset = separation_arcsec(a_correct, a_wrong)
    _, los_wrong = line_of_sight(sun, observer, a_wrong, z_au)
    wrong_ra, wrong_dec = radec_deg(a_wrong)
    los_wrong_ra, los_wrong_dec = radec_deg(los_wrong)
    out["double_retarded_rx"] = {
        "catalog_epoch_u_days": fmt(u_wrong),
        "target_dir_ra_deg": fmt(wrong_ra),
        "target_dir_dec_deg": fmt(wrong_dec),
        "los_ra_deg": fmt(los_wrong_ra),
        "los_dec_deg": fmt(los_wrong_dec),
        "offset_from_correct_rx_arcsec": fmt(offset),
        "expected_offset_arcsec_approx": fmt(
            mu_rad_per_day * (d_au / C_AU_PER_DAY) * ARCSEC_PER_RAD
        ),
    }
    return out


def main() -> None:
    print(json.dumps(
        {
            "c_au_per_day": fmt(C_AU_PER_DAY),
            "static": fixture_static(),
            "constant_velocity": fixture_constant_velocity(),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
