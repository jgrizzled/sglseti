from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml


class CatalogError(RuntimeError):
    pass


def _value(row: Any, candidates: tuple[str, ...]) -> float:
    names = {name.lower(): name for name in row.colnames}
    for candidate in candidates:
        actual = names.get(candidate.lower())
        if actual is None:
            continue
        value = row[actual]
        try:
            if getattr(value, "mask", False):
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    raise CatalogError(
        f"SIMBAD result lacked any usable field in {candidates}; returned columns were {row.colnames}."
    )


def simbad_target_yaml(name: str, target_id: str) -> str:
    """Resolve one explicitly named object and emit a frozen target-registry block.

    This command never performs a neighborhood query. The result is a starting
    point only: binary systems and sub-arcsecond work require a vetted barycenter
    or component ephemeris rather than a generic name-resolver row.
    """

    try:
        from astroquery.simbad import Simbad
    except ImportError as exc:
        raise CatalogError(
            "astroquery is required for SIMBAD resolution. Install with "
            "'python -m pip install -e .[catalog]'."
        ) from exc

    simbad = Simbad()
    simbad.add_votable_fields("propermotions", "parallax", "velocity")
    table = simbad.query_object(name)
    if table is None or len(table) == 0:
        raise CatalogError(f"SIMBAD did not resolve {name!r}.")
    row = table[0]
    main_id = str(row["main_id"]).strip() if "main_id" in row.colnames else name
    block = {
        "schema_version": 1,
        "targets": {
            target_id: {
                "display_name": main_id,
                "priority": 1.0,
                "tags": ["unvetted-simbad-import"],
                "notes": (
                    "Generated from one explicit SIMBAD lookup. Verify the astrometric "
                    "reference epoch and use a system barycenter/orbital solution for binaries."
                ),
                "astrometry": {
                    "ra_deg": _value(row, ("ra",)),
                    "dec_deg": _value(row, ("dec",)),
                    "parallax_mas": _value(row, ("plx_value", "plx")),
                    "pm_ra_cosdec_mas_per_yr": _value(row, ("pmra", "pm_ra")),
                    "pm_dec_mas_per_yr": _value(row, ("pmdec", "pmde", "pm_dec")),
                    "radial_velocity_km_s": _value(
                        row, ("rvz_radvel", "radial_velocity")
                    ),
                    "reference_epoch_jyear": 2000.0,
                    "source": (
                        "SIMBAD explicit-name lookup generated "
                        + datetime.now(timezone.utc).date().isoformat()
                    ),
                },
            }
        },
    }
    return yaml.safe_dump(block, sort_keys=False)
