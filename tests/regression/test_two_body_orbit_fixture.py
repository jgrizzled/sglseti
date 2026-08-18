"""``two_body_orbit_v1`` verified against independent published-orbit offsets.

Roadmap §2.1 acceptance: at least one resolved-binary component and one
system-barycenter fixture verified against an independent ephemeris or
published orbital solution. The frozen fixture
(``two_body_orbit_reference.yaml``) carries offsets for the published
Alpha Centauri AB solution (Pourbaix & Boffin 2016, via Akeson et al. 2021
Table 8) and Sirius AB solution (Bond et al. 2017, Table 4), computed by an
INDEPENDENT implementation (Thiele-Innes constants, bisection Kepler
solver) in ``two_body_orbit_reference.py``.

External anchors: the fixture reproduces the widely observed ~4 arcsec
Alpha Cen A-B separation near PA ~300 deg in 2016 and the ~11 arcsec
maximum Sirius A-B separation near the 2019.64 apastron.
"""

from __future__ import annotations

import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from support import load_reference_fixture

from sglseti.models import (
    AstrometricState,
    EndpointKind,
    OrbitComponent,
    OrbitSolution,
    Target,
)
from sglseti.providers import LinearAstrometryV1, TargetState, TwoBodyOrbitV1

FIXTURE = load_reference_fixture("two_body_orbit_reference.yaml")

# Barycenter astrometry for the propagation. The orbital-offset comparison
# is independent of these values (the identical barycenter state underlies
# both sides), so position/proper-motion are demonstration-quality
# snapshots; parallax and radial velocity carry their published sources.
BARYCENTER_ASTROMETRY = {
    "alpha_cen_ab": AstrometricState(
        ra_deg=219.90206543,
        dec_deg=-60.83399269,
        pm_ra_cosdec_mas_per_yr=-3620.0,
        pm_dec_mas_per_yr=694.0,
        reference_epoch_jyear=2000.0,
        reference_epoch_scale="tdb",
        parallax_mas=743.0,
        radial_velocity_km_s=-22.390,
        source=(
            "demonstration barycenter snapshot; parallax 743 mas and "
            "systemic RV -22.390 km/s from Pourbaix & Boffin 2016 as "
            "tabulated by Akeson et al. 2021 Table 8"
        ),
    ),
    "sirius_ab": AstrometricState(
        ra_deg=101.28715533,
        dec_deg=-16.71611586,
        pm_ra_cosdec_mas_per_yr=-546.0,
        pm_dec_mas_per_yr=-1223.1,
        reference_epoch_jyear=2000.0,
        reference_epoch_scale="tdb",
        parallax_mas=378.9,
        radial_velocity_km_s=-5.5,
        source=(
            "demonstration barycenter snapshot; parallax 378.9 mas from "
            "Bond et al. 2017 (adopted weighted mean)"
        ),
    ),
}


def _orbit(system: str, component: OrbitComponent) -> OrbitSolution:
    data = FIXTURE["systems"][system]
    return OrbitSolution(
        component=component,
        mass_fraction_secondary=data["mass_fraction_secondary"],
        source=data["source"],
        **data["elements"],
    )


def _target(system: str, component: OrbitComponent) -> Target:
    endpoint = (
        EndpointKind.BARYCENTER
        if component is OrbitComponent.BARYCENTER
        else EndpointKind.COMPONENT
    )
    return Target(
        target_id=f"{system}-{component.value}".replace("_", "-"),
        display_name=f"{system} {component.value}",
        endpoint_kind=endpoint,
        astrometry=BARYCENTER_ASTROMETRY[system],
        provider_id="two_body_orbit_v1",
        orbit=_orbit(system, component),
    )


def _offset_arcsec(origin: TargetState, state: TargetState) -> tuple[float, float]:
    """(east=d_ra_cosdec, north=d_dec) offset between two states, arcsec."""
    a = SkyCoord(ra=origin.ra_deg * u.deg, dec=origin.dec_deg * u.deg)
    b = SkyCoord(ra=state.ra_deg * u.deg, dec=state.dec_deg * u.deg)
    d_lon, d_lat = a.spherical_offsets_to(b)
    return float(d_lon.to_value(u.arcsec)), float(d_lat.to_value(u.arcsec))


@pytest.mark.parametrize("system", sorted(FIXTURE["systems"]))
def test_component_offsets_match_independent_reference(system: str) -> None:
    data = FIXTURE["systems"][system]
    tolerance = FIXTURE["tolerance_arcsec"]
    fraction = data["mass_fraction_secondary"]
    barycenter = TwoBodyOrbitV1(_target(system, OrbitComponent.BARYCENTER))
    primary = TwoBodyOrbitV1(_target(system, OrbitComponent.PRIMARY))
    secondary = TwoBodyOrbitV1(_target(system, OrbitComponent.SECONDARY))
    for row in data["relative_offsets"]:
        epoch = Time(row["epoch_jyear"], format="jyear", scale="tdb")
        origin = barycenter.state_at(epoch)
        east_p, north_p = _offset_arcsec(origin, primary.state_at(epoch))
        east_s, north_s = _offset_arcsec(origin, secondary.state_at(epoch))
        north_rel = row["relative_north_arcsec"]
        east_rel = row["relative_east_arcsec"]
        assert north_p == pytest.approx(-fraction * north_rel, abs=tolerance)
        assert east_p == pytest.approx(-fraction * east_rel, abs=tolerance)
        assert north_s == pytest.approx((1.0 - fraction) * north_rel, abs=tolerance)
        assert east_s == pytest.approx((1.0 - fraction) * east_rel, abs=tolerance)


@pytest.mark.parametrize("system", sorted(FIXTURE["systems"]))
def test_barycenter_endpoint_reduces_to_linear(system: str) -> None:
    """The system-barycenter fixture: orbit family == plain linear exactly."""
    orbital = TwoBodyOrbitV1(_target(system, OrbitComponent.BARYCENTER))
    linear = LinearAstrometryV1(
        Target(
            target_id=f"{system}-linear".replace("_", "-"),
            display_name="linear barycenter",
            endpoint_kind=EndpointKind.BARYCENTER,
            astrometry=BARYCENTER_ASTROMETRY[system],
        )
    )
    for row in FIXTURE["systems"][system]["relative_offsets"]:
        epoch = Time(row["epoch_jyear"], format="jyear", scale="tdb")
        from_orbit = orbital.state_at(epoch)
        from_linear = linear.state_at(epoch)
        assert from_orbit.ra_deg == from_linear.ra_deg
        assert from_orbit.dec_deg == from_linear.dec_deg
        assert from_orbit.distance_au == from_linear.distance_au


def test_component_separations_match_published_context() -> None:
    """Coarse external anchors for the sky orientation and scale.

    Alpha Cen A-B was a widely observed ~4 arcsec pair around 2016 (the
    close approach documented by e.g. Kervella et al. 2016); Sirius A-B
    reached its ~11 arcsec maximum separation near the 2019.64 apastron of
    the Bond et al. 2017 orbit.
    """
    for system, epoch_jyear, low, high in (
        ("alpha_cen_ab", 2016.0, 3.9, 4.2),
        ("sirius_ab", 2019.6357, 10.9, 11.4),
    ):
        epoch = Time(epoch_jyear, format="jyear", scale="tdb")
        primary = TwoBodyOrbitV1(_target(system, OrbitComponent.PRIMARY))
        secondary = TwoBodyOrbitV1(_target(system, OrbitComponent.SECONDARY))
        a = primary.state_at(epoch)
        b = secondary.state_at(epoch)
        separation = float(
            SkyCoord(a.ra_deg * u.deg, a.dec_deg * u.deg)
            .separation(SkyCoord(b.ra_deg * u.deg, b.dec_deg * u.deg))
            .to_value(u.arcsec)
        )
        assert low < separation < high, (system, separation)


def test_orbit_is_periodic() -> None:
    """Offsets repeat after exactly one period (Sirius: T0 vs T0 + P)."""
    data = FIXTURE["systems"]["sirius_ab"]
    period = data["elements"]["period_yr"]
    t0 = data["elements"]["periastron_epoch_jyear"]
    provider = TwoBodyOrbitV1(_target("sirius_ab", OrbitComponent.SECONDARY))
    barycenter = TwoBodyOrbitV1(_target("sirius_ab", OrbitComponent.BARYCENTER))
    first = _offset_arcsec(
        barycenter.state_at(Time(t0, format="jyear", scale="tdb")),
        provider.state_at(Time(t0, format="jyear", scale="tdb")),
    )
    later = _offset_arcsec(
        barycenter.state_at(Time(t0 + period, format="jyear", scale="tdb")),
        provider.state_at(Time(t0 + period, format="jyear", scale="tdb")),
    )
    assert first == pytest.approx(later, abs=1e-6)
