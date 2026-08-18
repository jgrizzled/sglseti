import pytest

astropy = pytest.importorskip("astropy")

from sgl_search.config import Site, Target, TargetAstrometry
from sgl_search.geometry import GeometryEngine


def test_geometry_returns_finite_coordinates():
    target = Target(
        target_id="barnard",
        display_name="Barnard's Star",
        priority=1.0,
        tags=(),
        notes="",
        astrometry=TargetAstrometry(
            ra_deg=269.45207695861876,
            dec_deg=4.693364966576667,
            parallax_mas=546.9759,
            pm_ra_cosdec_mas_per_yr=-801.551,
            pm_dec_mas_per_yr=10362.394,
            radial_velocity_km_s=-110.11,
            reference_epoch_jyear=2000.0,
            source="test",
        ),
    )
    site = Site("test", -111.6, 31.95, 2000)
    engine = GeometryEngine(iers_auto_download=False)
    time = engine.time("2026-12-15T08:00:00")
    point = engine.probe_point(target, "receiver", 1000.0, time, engine.site_location(site))
    assert point.geometric_icrs.ra.deg == pytest.approx(point.geometric_icrs.ra.deg)
    assert -90 <= point.geometric_icrs.dec.deg <= 90
