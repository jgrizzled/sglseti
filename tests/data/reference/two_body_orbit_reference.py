"""Independent reference offsets for the ``two_body_orbit_v1`` provider.

Generates ``two_body_orbit_reference.yaml``: relative-orbit sky offsets
(secondary from primary, arcsec north/east, position angles east of north)
for two published visual-binary solutions, computed INDEPENDENTLY of the
package implementation:

- the package solves Kepler's equation by Newton-Raphson and rotates the
  true-anomaly in-plane position through the Campbell angles;
- this script solves Kepler's equation by BISECTION and builds the sky
  offsets from the THIELE-INNES constants A, B, F, G acting on the
  elliptical rectangular coordinates (X, Y) — a different derivation and a
  different solver, so agreement is a genuine cross-check of both.

Published orbital solutions (documented sources, frozen here):

- Alpha Centauri AB — Pourbaix & Boffin 2016, A&A 586, A90, as tabulated
  by Akeson et al. 2021, AJ 162, 14 (Table 8): P = 79.91 yr, T0 = 1955.66,
  e = 0.524, a = 17.66 arcsec, i = 79.32 deg, Omega = 204.85 deg,
  omega = 232.3 deg; mass fraction m_A/(m_A+m_B) = 0.5383.
- Sirius AB — Bond et al. 2017, ApJ 840, 70 (Table 4): P = 50.1284 yr,
  T0 = 1994.5715, e = 0.59142, a = 7.4957 arcsec, i = 136.336 deg,
  Omega = 45.400 deg, omega = 149.161 deg; masses M_A = 2.063 Msun,
  M_B = 1.018 Msun.

Run from the repository root to regenerate the frozen fixture:

    uv run python tests/data/reference/two_body_orbit_reference.py
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

TOLERANCE_ARCSEC = 1e-6  # documented comparison tolerance (1 micro-arcsec)

SYSTEMS: dict[str, dict[str, object]] = {
    "alpha_cen_ab": {
        "source": (
            "Pourbaix & Boffin 2016, A&A 586, A90, as tabulated by "
            "Akeson et al. 2021, AJ 162, 14, Table 8"
        ),
        "elements": {
            "period_yr": 79.91,
            "periastron_epoch_jyear": 1955.66,
            "eccentricity": 0.524,
            "semimajor_axis_arcsec": 17.66,
            "inclination_deg": 79.32,
            "ascending_node_deg": 204.85,
            "arg_periastron_deg": 232.3,
        },
        # Akeson et al. 2021 Table 8 tabulates m_A/(m_A+m_B) = 0.5383.
        "mass_fraction_secondary": 1.0 - 0.5383,
        # Includes 2016.0 (separation was a widely observed ~4 arcsec) and
        # the next periastron passage T0 + P = 2035.57.
        "epochs_jyear": [1975.0, 2000.0, 2016.0, 2035.57, 2050.25],
    },
    "sirius_ab": {
        "source": "Bond et al. 2017, ApJ 840, 70, Table 4",
        "elements": {
            "period_yr": 50.1284,
            "periastron_epoch_jyear": 1994.5715,
            "eccentricity": 0.59142,
            "semimajor_axis_arcsec": 7.4957,
            "inclination_deg": 136.336,
            "ascending_node_deg": 45.4,
            "arg_periastron_deg": 149.161,
        },
        # Bond et al. 2017 dynamical masses: 2.063 and 1.018 Msun.
        "mass_fraction_secondary": 1.018 / (2.063 + 1.018),
        # Includes the periastron epoch, the apastron epoch T0 + P/2 =
        # 2019.6357 (the widely observed ~11 arcsec maximum separation
        # around 2019), and the next periastron T0 + P.
        "epochs_jyear": [1994.5715, 2005.0, 2019.6357, 2030.0, 2044.6999],
    },
}


def kepler_bisect(mean_anomaly: float, eccentricity: float) -> float:
    """Solve E - e sin E = M by bisection (|E - M| <= e brackets the root)."""
    mean = math.remainder(mean_anomaly, math.tau)
    low, high = mean - eccentricity, mean + eccentricity

    def f(ecc_anom: float) -> float:
        return ecc_anom - eccentricity * math.sin(ecc_anom) - mean

    for _ in range(200):
        mid = 0.5 * (low + high)
        if f(mid) <= 0.0:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def thiele_innes_offset(elements: dict[str, float], epoch_jyear: float) -> tuple[float, float]:
    """(north, east) offset of the secondary from the primary, arcsec.

    Thiele-Innes formulation: x = AX + FY (north), y = BX + GY (east) with
    X = cos E - e and Y = sqrt(1 - e^2) sin E.
    """
    a = elements["semimajor_axis_arcsec"]
    ecc = elements["eccentricity"]
    node = math.radians(elements["ascending_node_deg"])
    omega = math.radians(elements["arg_periastron_deg"])
    incl = math.radians(elements["inclination_deg"])

    cos_o, sin_o = math.cos(omega), math.sin(omega)
    cos_n, sin_n = math.cos(node), math.sin(node)
    cos_i = math.cos(incl)
    const_a = a * (cos_o * cos_n - sin_o * sin_n * cos_i)
    const_b = a * (cos_o * sin_n + sin_o * cos_n * cos_i)
    const_f = a * (-sin_o * cos_n - cos_o * sin_n * cos_i)
    const_g = a * (-sin_o * sin_n + cos_o * cos_n * cos_i)

    mean_anomaly = (
        math.tau * (epoch_jyear - elements["periastron_epoch_jyear"]) / elements["period_yr"]
    )
    ecc_anom = kepler_bisect(mean_anomaly, ecc)
    x = math.cos(ecc_anom) - ecc
    y = math.sqrt(1.0 - ecc * ecc) * math.sin(ecc_anom)
    north = const_a * x + const_f * y
    east = const_b * x + const_g * y
    return north, east


def main() -> None:
    output: dict[str, object] = {
        "generator": "tests/data/reference/two_body_orbit_reference.py",
        "method": (
            "Thiele-Innes constants with bisection Kepler solver, independent "
            "of the package's Newton-Raphson/Campbell-rotation implementation"
        ),
        "tolerance_arcsec": TOLERANCE_ARCSEC,
        "systems": {},
    }
    for name, system in SYSTEMS.items():
        elements = system["elements"]
        assert isinstance(elements, dict)
        offsets = []
        for epoch in system["epochs_jyear"]:  # type: ignore[union-attr]
            north, east = thiele_innes_offset(elements, float(epoch))
            offsets.append(
                {
                    "epoch_jyear": float(epoch),
                    "relative_north_arcsec": north,
                    "relative_east_arcsec": east,
                    "separation_arcsec": math.hypot(north, east),
                    "position_angle_deg": math.degrees(math.atan2(east, north)) % 360.0,
                }
            )
        output["systems"][name] = {  # type: ignore[index]
            "source": system["source"],
            "elements": dict(elements),
            "mass_fraction_secondary": float(system["mass_fraction_secondary"]),  # type: ignore[arg-type]
            "relative_offsets": offsets,
        }
    path = Path(__file__).with_name("two_body_orbit_reference.yaml")
    path.write_text(
        "# GENERATED by two_body_orbit_reference.py — do not edit by hand.\n"
        + yaml.safe_dump(output, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
