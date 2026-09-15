"""Frozen Wolf 359 crossing regression (§2.5 science gate).

Anchors the ``sun_star_axis_v1`` outbound crossing search to the published
Gillon, Burdanov & Wright 2022 optical campaign (MNRAS 513:L18), with the
pinned DE440s excerpt kernel and the independent no-sglseti oracle in
``wolf359_crossing_reference.py``. Three claims ride on the fixture:

1. REPRODUCIBILITY (tight): the engine reproduces the frozen
   minimum-impact-parameter epochs and ``b_min`` values.
2. EXPECTED DISAGREEMENT (frozen, explicit): the computed crossing epochs
   differ from the paper's published epochs by ~+10.6 h (2015) and
   ~+17.0 h (2019); at the published epochs the Earth sits OUTSIDE the
   paper's own 1.1 R_sun beam annulus. The disagreement is the expected
   result — a match against the published epochs would be a regression.
   See notes/published_sgl_search_validation.md for the analysis.
3. PUBLICATION CONSISTENCY (loose): the tx line of sight from the
   TRAPPIST-South site at the published 2015 epoch falls within arcseconds
   of the published field center (the pointing is insensitive to the
   crossing-epoch defect).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from support import load_reference_fixture

from sglseti.crossings import find_crossings, impact_parameter
from sglseti.ephemeris import AstropyEphemeris
from sglseti.geometry import Tusay2022Eq57V1, compute_relay_solution
from sglseti.models import (
    AstrometricState,
    CrossingsRequest,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    LinkDirection,
    Observer,
    Role,
    Target,
    TimeInterval,
    Validity,
)
from sglseti.targets import TargetRegistry

FIXTURE = load_reference_fixture("wolf359_crossing_reference.yaml")
KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / ("de440s_excerpt_2010-2035.bsp")

pytest.importorskip("jplephem")


def wolf359_target() -> Target:
    astrometry = FIXTURE["astrometry"]
    return Target(
        target_id="wolf-359",
        display_name="Wolf 359",
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
            source=(
                "Gaia EDR3 via SIMBAD (queried 2026-08-18), ICRS "
                "J2000-propagated; notes/published_sgl_search_validation.md"
            ),
        ),
    )


def ephemeris_spec() -> EphemerisSpec:
    return EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL))


@pytest.fixture(scope="module")
def crossing_events() -> dict[int, object]:
    request = CrossingsRequest(
        target_ids=("wolf-359",),
        link_directions=(LinkDirection.OUTBOUND,),
        intervals=tuple(
            TimeInterval(
                interval_id=f"conjunction-{year}",
                start=Time(f"{year}-08-01T00:00:00", scale="utc"),
                stop=Time(f"{year}-10-01T00:00:00", scale="utc"),
            )
            for year in sorted(FIXTURE["years"])
        ),
        observer=Observer.earth_center(),
        relay_distance_au=FIXTURE["relay_distance_au"],
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=5.0,
        refine_tolerance_s=10.0,
    )
    registry = TargetRegistry.from_targets((wolf359_target(),))
    result = find_crossings(request, registry, strict=True)
    by_year: dict[int, object] = {}
    for event in result.events:
        assert event.validity is not Validity.INVALID
        year = int(event.interval_id.split("-")[1])
        # Keep the deepest minimum of each conjunction window.
        current = by_year.get(year)
        if current is None or event.b_min_au < current.b_min_au:
            by_year[year] = event
    return by_year


@pytest.mark.parametrize("year", sorted(FIXTURE["years"]))
def test_engine_reproduces_frozen_minimum(crossing_events, year: int) -> None:
    frozen = FIXTURE["years"][year]
    event = crossing_events[year]
    t_ca = Time(event.t_ca_tdb_jd, format="jd", scale="tdb")
    frozen_t = Time(frozen["computed_crossing_tdb_jd"], format="jd", scale="tdb")
    assert abs(float((t_ca - frozen_t).sec)) < 60.0
    assert event.b_min_solar_radii == pytest.approx(frozen["computed_b_min_rsun"], abs=5e-3)


@pytest.mark.parametrize("year", sorted(FIXTURE["years"]))
def test_disagreement_with_published_epochs_is_preserved(crossing_events, year: int) -> None:
    """The known offset from the published epochs is the EXPECTED result."""
    frozen = FIXTURE["years"][year]
    event = crossing_events[year]
    published = Time(frozen["published_crossing_utc"], scale="utc")
    t_ca = Time(event.t_ca_tdb_jd, format="jd", scale="tdb")
    offset_hours = float((t_ca - published.tdb).to_value(u.h))
    assert offset_hours == pytest.approx(frozen["offset_from_published_hours"], abs=0.2)
    # A "fix" that reconciles us with the published epochs would be a
    # regression: at those epochs the Earth is outside the paper's own
    # 1.1 R_sun annulus.
    assert offset_hours > 5.0
    sample = impact_parameter(
        target=wolf359_target(),
        time=published,
        link_direction=LinkDirection.OUTBOUND,
        observer=Observer.earth_center(),
        z_au=FIXTURE["relay_distance_au"],
        ephemeris=AstropyEphemeris(ephemeris_spec()),
    )
    assert sample.b_solar_radii == pytest.approx(frozen["b_at_published_epoch_rsun"], abs=5e-2)
    assert sample.b_solar_radii > FIXTURE["published_annulus_rsun"]


def test_tx_pointing_matches_publication() -> None:
    from sglseti.ephemeris import AstropyEphemeris

    site = FIXTURE["trappist_south_site"]
    solution = compute_relay_solution(
        target=wolf359_target(),
        observation_time=Time(FIXTURE["years"][2015]["published_crossing_utc"], scale="utc"),
        z_au=FIXTURE["relay_distance_au"],
        role=Role.TX,
        observer=Observer.from_geodetic(
            "trappist-south", site["lon_deg"], site["lat_deg"], site["height_m"]
        ),
        ephemeris=AstropyEphemeris(ephemeris_spec()),
        model=Tusay2022Eq57V1(),
    )
    computed = SkyCoord(solution.los_icrs_ra_deg * u.deg, solution.los_icrs_dec_deg * u.deg)
    frozen = FIXTURE["tx_pointing_at_published_2015_epoch"]
    reference = SkyCoord(frozen["ra_deg"] * u.deg, frozen["dec_deg"] * u.deg)
    assert computed.separation(reference).to_value(u.arcsec) < 1.0
    published = FIXTURE["published_field_center"]
    field_center = SkyCoord(published["ra_deg"] * u.deg, published["dec_deg"] * u.deg)
    # Publication consistency: the paper's field center (their Table/Sec. 2)
    # sits ~2 arcsec from the reconstructed tx line of sight.
    assert computed.separation(field_center).to_value(u.arcsec) < 10.0
