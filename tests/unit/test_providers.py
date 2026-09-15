"""Provider protocols and baseline families (roadmap item 6.1).

The baselines must reproduce the previous inline geometry behavior exactly:
the linear family is compared against a direct astropy construction, and
the observer families against the ephemeris/site math they replaced.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris

from sglseti.geometry import Tusay2022Eq57V1, observer_barycentric_au
from sglseti.models import (
    AccelerationTerms,
    AstrometricState,
    EndpointKind,
    Observer,
    OrbitComponent,
    OrbitSolution,
    Role,
    Target,
)
from sglseti.providers import (
    EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL,
    LINEAR_PROPAGATION_SPAN_YEARS,
    WARN_MISSING_RV,
    AccelerationAstrometryV1,
    EarthCenterObserverV1,
    LinearAstrometryV1,
    ObserverStateProvider,
    TargetStateProvider,
    TerrestrialSiteObserverV1,
    TwoBodyOrbitV1,
    resolve_observer_state_provider,
    resolve_target_state_provider,
)

T_O = Time("2021-11-06T00:00:00", scale="utc")
EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
SITE = Observer.from_geodetic("gbt", -79.83983611, 38.43312222, 807.43)


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
    target_provider = LinearAstrometryV1(make_target())
    assert isinstance(target_provider, TargetStateProvider)
    earth = EarthCenterObserverV1(Observer.earth_center(), EPHEMERIS)
    site = TerrestrialSiteObserverV1(SITE, EPHEMERIS)
    assert isinstance(earth, ObserverStateProvider)
    assert isinstance(site, ObserverStateProvider)


def test_resolvers_pick_the_baseline_families() -> None:
    assert isinstance(resolve_target_state_provider(make_target()), LinearAstrometryV1)
    assert isinstance(
        resolve_observer_state_provider(Observer.earth_center(), EPHEMERIS),
        EarthCenterObserverV1,
    )
    assert isinstance(resolve_observer_state_provider(SITE, EPHEMERIS), TerrestrialSiteObserverV1)


def test_observer_providers_reject_mismatched_observer_kinds() -> None:
    with pytest.raises(ValueError, match="earth_center observer"):
        EarthCenterObserverV1(SITE, EPHEMERIS)
    with pytest.raises(ValueError, match="site observer"):
        TerrestrialSiteObserverV1(Observer.earth_center(), EPHEMERIS)


def test_linear_state_matches_direct_astropy_propagation() -> None:
    from astropy import units as u
    from astropy.coordinates import Distance, SkyCoord

    provider = LinearAstrometryV1(make_target())
    state = provider.state_at(T_O.tdb)
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
    assert state.ra_deg == float(direct.ra.deg)
    assert state.dec_deg == float(direct.dec.deg)
    assert state.distance_au == float(direct.distance.to_value(u.au))


def test_linear_metadata_is_declared() -> None:
    provider = LinearAstrometryV1(make_target())
    assert provider.provider_id == "linear_astrometry_v1"
    assert provider.provider_version == "1.0.0"
    assert provider.epoch_semantics == EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL
    assert provider.frame == "icrs"
    assert provider.origin == "ssb"
    assert provider.uncertainty_model == "not_propagated"
    assert provider.warnings == ()
    low, high = provider.validity_interval_jyear
    assert high - low == pytest.approx(2.0 * LINEAR_PROPAGATION_SPAN_YEARS)
    assert low < 2000.0 < high


def test_linear_missing_rv_is_a_solution_level_warning() -> None:
    provider = LinearAstrometryV1(make_target(radial_velocity_km_s=None, flags=(WARN_MISSING_RV,)))
    assert WARN_MISSING_RV in provider.warnings
    state = provider.state_at(T_O.tdb)
    assert np.isfinite(state.ra_deg) and np.isfinite(state.dec_deg)


def test_linear_content_hash_is_a_solution_identity() -> None:
    a = LinearAstrometryV1(make_target())
    b = LinearAstrometryV1(make_target())
    changed = LinearAstrometryV1(make_target(d_au=100_000.0))
    assert a.content_hash == b.content_hash
    assert a.content_hash != changed.content_hash
    assert "/" not in a.content_hash


def test_linear_propagation_span_years() -> None:
    provider = LinearAstrometryV1(make_target(reference_epoch_jyear=2000.0))
    epoch = Time(2050.0, format="jyear", scale="tdb")
    assert provider.propagation_span_years(epoch) == pytest.approx(50.0, abs=1e-6)


def test_earth_center_state_matches_ephemeris_earth() -> None:
    provider = EarthCenterObserverV1(Observer.earth_center(), EPHEMERIS)
    state = provider.state_at(T_O)
    assert np.array_equal(np.asarray(state.position_au), EPHEMERIS.earth_barycentric_au(T_O))
    assert state.velocity_au_per_day is None
    # And the geometry-level helper is the provider path.
    assert np.array_equal(
        observer_barycentric_au(Observer.earth_center(), T_O, EPHEMERIS),
        np.asarray(state.position_au),
    )


def test_site_state_offset_is_geocentric_radius() -> None:
    provider = TerrestrialSiteObserverV1(SITE, EPHEMERIS)
    state = provider.state_at(T_O)
    earth = EPHEMERIS.earth_barycentric_au(T_O)
    offset_km = float(np.linalg.norm(np.asarray(state.position_au) - earth)) * 149_597_870.7
    assert 6350.0 < offset_km < 6390.0  # geocentric radius at latitude 38.4
    assert np.array_equal(
        observer_barycentric_au(SITE, T_O, EPHEMERIS), np.asarray(state.position_au)
    )


def test_observer_metadata_is_declared() -> None:
    earth = EarthCenterObserverV1(Observer.earth_center(), EPHEMERIS)
    site = TerrestrialSiteObserverV1(SITE, EPHEMERIS)
    for provider in (earth, site):
        assert provider.frame == "icrs"
        assert provider.origin == "ssb"
        assert provider.time_scale == "tdb"
        assert provider.interpolation == "none"
        assert provider.coverage is None
        assert provider.provider_version == "1.0.0"
    assert earth.provider_id == "earth_center_v1"
    assert site.provider_id == "terrestrial_site_v1"
    assert earth.content_hash != site.content_hash
    # Identity covers the ephemeris and, for a site, its geodetic position.
    other_site = Observer.from_geodetic("gbt2", -79.83983611, 38.5, 807.43)
    assert TerrestrialSiteObserverV1(other_site, EPHEMERIS).content_hash != site.content_hash


def test_model_rejects_foreign_epoch_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PhysicalEpochProvider(LinearAstrometryV1):
        epoch_semantics = "physical_target_event_time"

    import sglseti.geometry as geometry

    monkeypatch.setattr(
        geometry,
        "resolve_target_state_provider",
        lambda target: PhysicalEpochProvider(target),
    )
    with pytest.raises(ValueError, match="epoch\\s+semantics"):
        Tusay2022Eq57V1().target_direction(make_target(), T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)


def test_model_output_unchanged_through_provider_path() -> None:
    """The model result equals a direct provider evaluation at its epochs."""
    model = Tusay2022Eq57V1()
    provider = LinearAstrometryV1(make_target())
    solution = model.target_direction(make_target(), T_O, 1000.0, Role.RX, EPHEMERIS)
    direct = provider.state_at(solution.catalog_direction_epoch)
    assert solution.target_direction_icrs_ra_deg == direct.ra_deg
    assert solution.target_direction_icrs_dec_deg == direct.dec_deg


# ---------------------------------------------------------------------------
# Registry-v2 provider families
# ---------------------------------------------------------------------------


def make_accel_target(accel_ra: float = 0.9, accel_dec: float = -0.4) -> Target:
    base = make_target()
    return Target(
        target_id="unit-accel",
        display_name="Accelerating Star",
        endpoint_kind=EndpointKind.STAR,
        astrometry=base.astrometry,
        provider_id="acceleration_astrometry_v1",
        acceleration=AccelerationTerms(
            accel_ra_cosdec_mas_per_yr2=accel_ra,
            accel_dec_mas_per_yr2=accel_dec,
            source="unit test values",
        ),
    )


def make_orbit_target(
    component: OrbitComponent,
    *,
    eccentricity: float = 0.524,
    inclination_deg: float = 79.32,
    mass_fraction: float = 0.4617,
) -> Target:
    base = make_target()
    endpoint = (
        EndpointKind.BARYCENTER
        if component is OrbitComponent.BARYCENTER
        else EndpointKind.COMPONENT
    )
    return Target(
        target_id=f"unit-orbit-{component.value}",
        display_name="Binary endpoint",
        endpoint_kind=endpoint,
        astrometry=base.astrometry,
        provider_id="two_body_orbit_v1",
        orbit=OrbitSolution(
            period_yr=79.91,
            periastron_epoch_jyear=1955.66,
            eccentricity=eccentricity,
            semimajor_axis_arcsec=17.66,
            inclination_deg=inclination_deg,
            ascending_node_deg=204.85,
            arg_periastron_deg=232.3,
            mass_fraction_secondary=mass_fraction,
            component=component,
            source="unit test values",
        ),
    )


def _sky(state: object) -> object:
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    return SkyCoord(ra=state.ra_deg * u.deg, dec=state.dec_deg * u.deg)  # type: ignore[attr-defined]


def test_resolver_dispatches_by_provider_id() -> None:
    assert isinstance(resolve_target_state_provider(make_target()), LinearAstrometryV1)
    accel = resolve_target_state_provider(make_accel_target())
    assert type(accel) is AccelerationAstrometryV1
    orbit = resolve_target_state_provider(make_orbit_target(OrbitComponent.PRIMARY))
    assert type(orbit) is TwoBodyOrbitV1
    assert isinstance(accel, TargetStateProvider)
    assert isinstance(orbit, TargetStateProvider)


def test_new_family_constructors_require_their_blocks() -> None:
    with pytest.raises(ValueError, match="acceleration terms"):
        AccelerationAstrometryV1(make_target())
    with pytest.raises(ValueError, match="orbit solution"):
        TwoBodyOrbitV1(make_target())


def test_content_hashes_distinguish_families() -> None:
    linear = LinearAstrometryV1(make_target())
    accel = AccelerationAstrometryV1(make_accel_target())
    orbit = TwoBodyOrbitV1(make_orbit_target(OrbitComponent.PRIMARY))
    hashes = {linear.content_hash, accel.content_hash, orbit.content_hash}
    assert len(hashes) == 3
    # And the hash tracks the adopted solution, not just the family.
    other = AccelerationAstrometryV1(make_accel_target(accel_ra=1.1))
    assert other.content_hash != accel.content_hash


def test_acceleration_is_zero_at_reference_epoch() -> None:
    from astropy import units as u

    reference = Time(2000.0, format="jyear", scale="tdb")
    linear = LinearAstrometryV1(make_target()).state_at(reference)
    accelerated = AccelerationAstrometryV1(make_accel_target()).state_at(reference)
    shift = _sky(linear).separation(_sky(accelerated)).to_value(u.arcsec)
    assert shift == pytest.approx(0.0, abs=1e-9)


def test_acceleration_offset_grows_quadratically() -> None:
    from astropy import units as u

    linear = LinearAstrometryV1(make_target())
    accelerated = AccelerationAstrometryV1(make_accel_target())

    def offset_mas(epoch_jyear: float) -> tuple[float, float]:
        epoch = Time(epoch_jyear, format="jyear", scale="tdb")
        d_lon, d_lat = _sky(linear.state_at(epoch)).spherical_offsets_to(
            _sky(accelerated.state_at(epoch))
        )
        return float(d_lon.to_value(u.mas)), float(d_lat.to_value(u.mas))

    at_10 = offset_mas(2010.0)
    at_20 = offset_mas(2020.0)
    # 0.5 * a * dt^2 with a = (0.9, -0.4) mas/yr^2: (45, -20) mas at dt=10.
    assert at_10[0] == pytest.approx(45.0, abs=1e-3)
    assert at_10[1] == pytest.approx(-20.0, abs=1e-3)
    assert at_20[0] == pytest.approx(4.0 * at_10[0], rel=1e-6)
    assert at_20[1] == pytest.approx(4.0 * at_10[1], rel=1e-6)


def test_circular_faceon_orbit_has_constant_separation() -> None:
    from astropy import units as u

    primary = TwoBodyOrbitV1(
        make_orbit_target(OrbitComponent.PRIMARY, eccentricity=0.0, inclination_deg=0.0)
    )
    secondary = TwoBodyOrbitV1(
        make_orbit_target(OrbitComponent.SECONDARY, eccentricity=0.0, inclination_deg=0.0)
    )
    for epoch_jyear in (1990.0, 2003.7, 2017.2, 2042.9):
        epoch = Time(epoch_jyear, format="jyear", scale="tdb")
        separation = (
            _sky(primary.state_at(epoch))
            .separation(_sky(secondary.state_at(epoch)))
            .to_value(u.arcsec)
        )
        assert separation == pytest.approx(17.66, abs=1e-4)


def test_orbit_metadata_and_linear_inheritance() -> None:
    provider = TwoBodyOrbitV1(make_orbit_target(OrbitComponent.SECONDARY))
    assert provider.provider_id == "two_body_orbit_v1"
    assert provider.epoch_semantics == EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL
    assert provider.uncertainty_model == "not_propagated"
    assert "tangential_orbit_offset_only" in provider.approximations
    # Validity is still bounded by the linear barycenter solution.
    low, high = provider.validity_interval_jyear
    assert high - low == pytest.approx(2.0 * LINEAR_PROPAGATION_SPAN_YEARS)
