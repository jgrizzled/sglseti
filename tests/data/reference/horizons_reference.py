"""Fetch and freeze JPL Horizons cross-validation data (§2.5).

ONE-TIME ONLINE generator (the only network-touching script in the test
tree; the tests read only the frozen YAML). Queries the JPL Horizons API
for an independent construction of Earth-based positions:

- barycentric ICRF position vectors of the Sun and the Earth geocenter
  (center ``500@0``, AU, TDB epochs) — validates the ephemeris adapters;
- astrometric ICRF RA/Dec of the Sun as seen from the Earth geocenter and
  from the Green Bank site — validates the full observer + ephemeris +
  direction pipeline. Horizons astrometric coordinates are light-time
  corrected: the Sun's barycentric motion over one light-time (~6-8 km)
  displaces the direction by up to ~11 mas, so the tight comparison
  applies the same retardation on the sglseti side; the residual against
  the UNRETARDED geometric direction is itself a measured light-time term
  and is asserted at its expected ~mas scale.

Six epochs span the DE440s excerpt kernel coverage (2013-2030), including
the two published-search anchors (2015-09-05, 2021-11-06).

Run from the repository root to regenerate the frozen fixture:

    uv run python tests/data/reference/horizons_reference.py
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

API = "https://ssd.jpl.nasa.gov/api/horizons.api"

#: TDB Julian dates for vector tables; the same instants are queried as UT
#: Julian dates for the observer tables (each table records its own scale).
EPOCH_JDS = [
    2456293.5,  # 2013-01-01
    2457270.5,  # 2015-09-05 (Gillon et al. 2015 campaign conjunction)
    2458284.5,  # 2018-06-15
    2459524.5,  # 2021-11-06 (Tusay et al. GBT session)
    2460735.5,  # 2025-03-01
    2462502.5,  # 2030-01-01
]

GREEN_BANK = {"lon_deg": -79.83983611, "lat_deg": 38.43312222, "height_m": 807.43}


def query(params: dict[str, str]) -> str:
    base = {
        "format": "text",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "TLIST": "'" + ",".join(f"{jd:.1f}" for jd in EPOCH_JDS) + "'",
        "TLIST_TYPE": "'JD'",
    }
    base.update(params)
    url = API + "?" + urllib.parse.urlencode(base)
    with urllib.request.urlopen(url, timeout=60) as response:
        text = response.read().decode("utf-8")
    if "$$SOE" not in text:
        raise RuntimeError(f"Horizons returned no ephemeris block:\n{text[:2000]}")
    return text.split("$$SOE")[1].split("$$EOE")[0]


def fetch_vectors(command: str) -> list[dict[str, float]]:
    block = query(
        {
            "COMMAND": f"'{command}'",
            "EPHEM_TYPE": "'VECTORS'",
            "CENTER": "'500@0'",
            "REF_PLANE": "'FRAME'",
            "REF_SYSTEM": "'ICRF'",
            "VEC_TABLE": "'1'",
            "OUT_UNITS": "'AU-D'",
            "TIME_TYPE": "'TDB'",
        }
    )
    rows = []
    pattern = re.compile(
        r"^(?P<jd>\d+\.\d+) = .*?$\s*"
        r"X =\s*(?P<x>[-+0-9.E]+)\s*Y =\s*(?P<y>[-+0-9.E]+)\s*Z =\s*(?P<z>[-+0-9.E]+)",
        re.MULTILINE,
    )
    for match in pattern.finditer(block):
        rows.append(
            {
                "tdb_jd": float(match.group("jd")),
                "x_au": float(match.group("x")),
                "y_au": float(match.group("y")),
                "z_au": float(match.group("z")),
            }
        )
    if len(rows) != len(EPOCH_JDS):
        raise RuntimeError(f"expected {len(EPOCH_JDS)} vector rows, got {len(rows)}")
    return rows


def fetch_sun_astrometric(center: str, extra: dict[str, str]) -> list[dict[str, float]]:
    params = {
        "COMMAND": "'10'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": f"'{center}'",
        "QUANTITIES": "'1'",  # astrometric ICRF RA/Dec, light-time corrected
        "ANG_FORMAT": "'DEG'",
        "EXTRA_PREC": "'YES'",
        "TIME_TYPE": "'UT'",
        "CSV_FORMAT": "'YES'",
    }
    params.update(extra)
    block = query(params)
    rows = []
    for jd, line in zip(EPOCH_JDS, [ln for ln in block.splitlines() if ln.strip()], strict=True):
        cells = [cell.strip() for cell in line.split(",")]
        # CSV observer rows: date, [flags...], RA, Dec — RA/Dec are the last
        # two non-empty numeric cells.
        numeric = [c for c in cells[1:] if re.fullmatch(r"[-+0-9.]+", c)]
        rows.append({"ut_jd": jd, "ra_deg": float(numeric[-2]), "dec_deg": float(numeric[-1])})
    return rows


def main() -> None:
    site = GREEN_BANK
    output = {
        "generator": "tests/data/reference/horizons_reference.py",
        "source": "JPL Horizons API (ssd.jpl.nasa.gov/api/horizons.api), DE441",
        "fetched": "2026-08-18",
        "conventions": {
            "vectors": "barycentric ICRF, AU, TDB epochs, center 500@0",
            "astrometric": (
                "ICRF RA/Dec of the Sun, light-time corrected (~11 mas "
                "displacement for the Sun's barycentric motion), UT epochs"
            ),
        },
        "green_bank_site": dict(site),
        "sun_barycentric": fetch_vectors("10"),
        "earth_barycentric": fetch_vectors("399"),
        "sun_astrometric_geocenter": fetch_sun_astrometric("500@399", {}),
        "sun_astrometric_green_bank": fetch_sun_astrometric(
            "coord@399",
            {
                "COORD_TYPE": "'GEODETIC'",
                "SITE_COORD": (
                    f"'{site['lon_deg']},{site['lat_deg']},{site['height_m'] / 1000.0}'"
                ),
            },
        ),
    }
    path = Path(__file__).with_name("horizons_reference.yaml")
    path.write_text(
        "# GENERATED by horizons_reference.py (one-time online fetch) — do\n"
        "# not edit by hand.\n" + yaml.safe_dump(output, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
