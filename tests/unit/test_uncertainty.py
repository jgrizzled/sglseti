"""Propagated uncertainty products (§2.3) and uncertainty-aware crossings (§3.3).

All sampling is seeded, so every statistical assertion here is
deterministic — bounds are generous only to stay robust under seed changes.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from astropy.time import Time
from support import FakeEphemeris, MovingEphemeris

from sglseti.crossings import minimize_impact_parameter
from sglseti.errors import GenerationError
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.models import (
    AstrometricState,
    BeamSide,
    CovarianceKind,
    CovarianceSpec,
    CrossingsRequest,
    EndpointKind,
    LinkDirection,
    ObservationInterval,
    Observer,
    OrbitComponent,
    OrbitSolution,
    ParameterProvenance,
    Role,
    Target,
    TimeInterval,
    UncertaintyMethod,
    Validity,
)
from sglseti.targets import TargetRegistry
from sglseti.uncertainty import (
    CONTRIBUTION_TARGET_STATE,
    WARN_DEGRADED_SAMPLES,
    WARN_MINIMUM_AT_WINDOW_EDGE,
    crossing_uncertainty,
    draw_target_samples,
    propagate_locus_uncertainty,
    target_uncertainty,
)

MODEL = Tusay2022Eq57V1()
T_O = Time("2021-11-06T00:00:00", scale="utc")
EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
OBSERVER = Observer.earth_center()


def provenance(**sigmas: tuple[float, str]) -> tuple[ParameterProvenance, ...]:
    return tuple(
        ParameterProvenance(
            parameter=name, source="unit test", uncertainty=value, unit=unit
        )
        for name, (value, unit) in sigmas.items()
    )


def make_target(
    *,
    parameter_provenance: tuple[ParameterProvenance, ...] = (),
    covariance: CovarianceSpec | None = None,
    pm: tuple[float, float] = (0.0, 0.0),
) -> Target:
    return Target(
        target_id="unit-test",
        display_name="Unit Test Star",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=pm[0],
            pm_dec_mas_per_yr=pm[1],
            reference_epoch_jyear=2000.0,
            reference_epoch_scale="tdb",
            source="unit test values",
            parallax_mas=100.0,
            radial_velocity_km_s=0.0,
        ),
        parameter_provenance=parameter_provenance,
        covariance=covariance,
    )


def make_orbit_target(
    *,
    parameter_provenance: tuple[ParameterProvenance, ...],
    eccentricity: float = 0.5,
    mass_fraction: float = 0.5,
) -> Target:
    base = make_target()
    return Target(
        target_id="unit-orbit",
        display_name="Binary component",
        endpoint_kind=EndpointKind.COMPONENT,
        astrometry=base.astrometry,
        provider_id="two_body_orbit_v1",
        orbit=OrbitSolution(
            period_yr=79.91,
            periastron_epoch_jyear=1955.66,
            eccentricity=eccentricity,
            semimajor_axis_arcsec=17.66,
            inclination_deg=79.32,
            ascending_node_deg=204.85,
            arg_periastron_deg=232.3,
            mass_fraction_secondary=mass_fraction,
            component=OrbitComponent.PRIMARY,
            source="unit test values",
        ),
        parameter_provenance=parameter_provenance,
    )


# ---------------------------------------------------------------------------
# Sampling-model assembly
# ---------------------------------------------------------------------------


def test_no_uncertainties_is_an_error() -> None:
    with pytest.raises(GenerationError, match="no usable uncertainties"):
        target_uncertainty(make_target())


def test_unit_mismatch_is_an_error() -> None:
    target = make_target(
        parameter_provenance=provenance(parallax_mas=(0.5, "arcsec"))
    )
    with pytest.raises(GenerationError, match="requires 'mas'"):
        target_uncertainty(target)


def test_correlation_requires_provenance_sigmas() -> None:
    covariance = CovarianceSpec(
        parameters=("pm_ra_cosdec_mas_per_yr", "pm_dec_mas_per_yr"),
        units=("mas/yr", "mas/yr"),
        kind=CovarianceKind.CORRELATION,
        matrix=((1.0, -0.6), (-0.6, 1.0)),
    )
    with pytest.raises(GenerationError, match="needs provenance uncertainties"):
        target_uncertainty(make_target(covariance=covariance))


def test_unsampleable_covariance_parameter_is_an_error() -> None:
    covariance = CovarianceSpec(
        parameters=("ra", "dec"),
        units=("mas", "mas"),
        kind=CovarianceKind.COVARIANCE,
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    with pytest.raises(GenerationError, match="not a sampleable parameter"):
        target_uncertainty(make_target(covariance=covariance))


def test_conflicting_sigma_declarations_are_an_error() -> None:
    covariance = CovarianceSpec(
        parameters=("parallax_mas",),
        units=("mas",),
        kind=CovarianceKind.COVARIANCE,
        matrix=((4.0,),),  # sigma 2
    )
    target = make_target(
        parameter_provenance=provenance(parallax_mas=(5.0, "mas")),
        covariance=covariance,
    )
    with pytest.raises(GenerationError, match="resolve the ambiguity"):
        target_uncertainty(target)


def test_correlation_assembles_covariance() -> None:
    covariance = CovarianceSpec(
        parameters=("pm_ra_cosdec_mas_per_yr", "pm_dec_mas_per_yr"),
        units=("mas/yr", "mas/yr"),
        kind=CovarianceKind.CORRELATION,
        matrix=((1.0, -0.6), (-0.6, 1.0)),
    )
    target = make_target(
        parameter_provenance=provenance(
            pm_ra_cosdec_mas_per_yr=(10.0, "mas/yr"),
            pm_dec_mas_per_yr=(20.0, "mas/yr"),
        ),
        covariance=covariance,
    )
    model = target_uncertainty(target)
    assert model.parameters == ("pm_ra_cosdec_mas_per_yr", "pm_dec_mas_per_yr")
    assert model.covariance[0][0] == pytest.approx(100.0)
    assert model.covariance[1][1] == pytest.approx(400.0)
    assert model.covariance[0][1] == pytest.approx(-0.6 * 10.0 * 20.0)
    assert model.sigmas == (pytest.approx(10.0), pytest.approx(20.0))


# ---------------------------------------------------------------------------
# Target sampling
# ---------------------------------------------------------------------------


def test_sampling_is_deterministic_per_seed() -> None:
    target = make_target(parameter_provenance=provenance(parallax_mas=(5.0, "mas")))
    first = draw_target_samples(target, count=8, seed=42)
    second = draw_target_samples(target, count=8, seed=42)
    other = draw_target_samples(target, count=8, seed=43)
    assert first == second
    assert first != other


def test_sampled_statistics_match_declared_model() -> None:
    covariance = CovarianceSpec(
        parameters=("pm_ra_cosdec_mas_per_yr", "pm_dec_mas_per_yr"),
        units=("mas/yr", "mas/yr"),
        kind=CovarianceKind.CORRELATION,
        matrix=((1.0, -0.6), (-0.6, 1.0)),
    )
    target = make_target(
        parameter_provenance=provenance(
            parallax_mas=(5.0, "mas"),
            pm_ra_cosdec_mas_per_yr=(10.0, "mas/yr"),
            pm_dec_mas_per_yr=(20.0, "mas/yr"),
        ),
        covariance=covariance,
    )
    samples = draw_target_samples(target, count=1200, seed=7)
    parallaxes = np.array([s.astrometry.parallax_mas for s in samples])
    pm_ra = np.array([s.astrometry.pm_ra_cosdec_mas_per_yr for s in samples])
    pm_dec = np.array([s.astrometry.pm_dec_mas_per_yr for s in samples])
    assert float(np.mean(parallaxes)) == pytest.approx(100.0, abs=0.6)
    assert float(np.std(parallaxes, ddof=1)) == pytest.approx(5.0, rel=0.1)
    assert float(np.std(pm_ra, ddof=1)) == pytest.approx(10.0, rel=0.1)
    correlation = float(np.corrcoef(pm_ra, pm_dec)[0, 1])
    assert -0.72 < correlation < -0.48


def test_orbit_domain_rejection_keeps_samples_valid() -> None:
    target = make_orbit_target(
        parameter_provenance=provenance(eccentricity=(0.3, "1")),
        eccentricity=0.9,
    )
    samples = draw_target_samples(target, count=64, seed=11)
    eccentricities = [s.orbit.eccentricity for s in samples if s.orbit is not None]
    assert len(eccentricities) == 64
    assert all(0.0 <= e < 1.0 for e in eccentricities)


def test_hopeless_domain_rejection_fails_loudly() -> None:
    target = make_orbit_target(
        parameter_provenance=provenance(mass_fraction_secondary=(500.0, "1")),
    )
    with pytest.raises(GenerationError, match="rejection sampling failed"):
        draw_target_samples(target, count=8, seed=1)


# ---------------------------------------------------------------------------
# Propagated locus uncertainty
# ---------------------------------------------------------------------------


def locus_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        role=Role.ANTIPODE,
        observation_time=T_O,
        observer=OBSERVER,
        z_au=1000.0,
        ephemeris=EPHEMERIS,
        model=MODEL,
    )
    base.update(overrides)
    return base


def test_locus_uncertainty_reflects_declared_position_sigma() -> None:
    # 1000 mas of tangent-plane RA uncertainty maps ~1:1 onto the relay
    # direction, entirely in the east component.
    target = make_target(parameter_provenance=provenance(ra_deg=(1000.0, "mas")))
    result = propagate_locus_uncertainty(
        target=target, seed=5, count=400, **locus_kwargs()
    )
    offsets = np.array(result.offsets_arcsec)
    east_sigma = float(np.std(offsets[:, 0], ddof=1))
    north_sigma = float(np.std(offsets[:, 1], ddof=1))
    assert east_sigma == pytest.approx(1.0, rel=0.15)
    assert north_sigma < 0.05
    assert result.covariance_arcsec2[0][0] == pytest.approx(east_sigma**2, rel=1e-6)
    # Empirical 95% radius of a 1-D Gaussian: ~1.96 sigma.
    assert 1.7 < result.confidence_radius_arcsec < 2.3
    # Along/cross decomposition preserves total variance (orthonormal).
    total = result.covariance_arcsec2[0][0] + result.covariance_arcsec2[1][1]
    decomposed = (
        result.along_track_sigma_arcsec**2 + result.cross_track_sigma_arcsec**2
    )
    assert decomposed == pytest.approx(total, rel=1e-6)
    assert result.method is UncertaintyMethod.PROPAGATED
    assert CONTRIBUTION_TARGET_STATE in result.contributions
    assert result.sample_count == 400
    assert result.seed == 5
    assert result.distribution == "monte_carlo"
    assert result.validity is Validity.VALID


def test_locus_uncertainty_is_deterministic() -> None:
    target = make_target(parameter_provenance=provenance(ra_deg=(500.0, "mas")))
    first = propagate_locus_uncertainty(
        target=target, seed=9, count=64, **locus_kwargs()
    )
    second = propagate_locus_uncertainty(
        target=target, seed=9, count=64, **locus_kwargs()
    )
    assert first.offsets_arcsec == second.offsets_arcsec
    assert first.confidence_radius_arcsec == second.confidence_radius_arcsec


def test_locus_uncertainty_surfaces_degraded_samples() -> None:
    target = make_target(parameter_provenance=provenance(ra_deg=(500.0, "mas")))
    result = propagate_locus_uncertainty(
        target=target, seed=3, count=32, **locus_kwargs(z_au=500.0)
    )
    # Below the solar focal minimum every sample (and the nominal) is
    # degraded; the counts are surfaced, never averaged away.
    assert result.nominal.validity is Validity.DEGRADED
    assert result.degraded_sample_count == 32
    assert any(w.startswith(WARN_DEGRADED_SAMPLES) for w in result.warnings)


# ---------------------------------------------------------------------------
# Uncertainty-aware crossings
# ---------------------------------------------------------------------------


def crossing_scenario() -> tuple[Target, MovingEphemeris, Any]:
    """A controlled beam crossing: observer drifts past the axis.

    The axis points along the propagated target direction from the Sun;
    the observer track starts offset by 0.05 AU in one perpendicular
    direction (crossed at 0.001 AU/day, so t_ca ~ 50 days) with a constant
    0.02 AU offset in the other, giving b_min ~ 0.02 AU at s ~ 5 AU down
    the axis. The RA uncertainty tilts the axis along the crossing
    direction (perturbing t_ca), the Dec uncertainty along the constant
    offset (perturbing b_min); ~100 arcsec at s ~ 5 AU is ~2.4e-3 AU each.
    """
    target = make_target(
        parameter_provenance=provenance(
            ra_deg=(100_000.0, "mas"), dec_deg=(100_000.0, "mas")
        )
    )
    axis = np.array(
        [
            math.cos(math.radians(20.0)) * math.cos(math.radians(10.0)),
            math.cos(math.radians(20.0)) * math.sin(math.radians(10.0)),
            math.sin(math.radians(20.0)),
        ]
    )
    perp_1 = np.cross(axis, [0.0, 0.0, 1.0])
    perp_1 /= np.linalg.norm(perp_1)
    perp_2 = np.cross(axis, perp_1)
    perp_2 /= np.linalg.norm(perp_2)
    sun = np.array([0.004, -0.002, 0.001])
    base = sun + 5.0 * axis + 0.05 * perp_1 + 0.02 * perp_2
    velocity = -0.001 * perp_1
    ephemeris = MovingEphemeris(
        tuple(velocity), base_time=T_O, base_earth_au=tuple(base), sun_au=tuple(sun)
    )
    request = CrossingsRequest(
        target_ids=("unit-test",),
        link_directions=(LinkDirection.INBOUND,),
        intervals=(TimeInterval(interval_id="i1", start=T_O, stop=T_O + 100.0),),
        observer=OBSERVER,
        relay_distance_au=1000.0,
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=10.0,
    )
    return target, ephemeris, request


def test_crossing_uncertainty_distribution() -> None:
    from sglseti.crossings import find_crossings

    target, ephemeris, request = crossing_scenario()
    registry = TargetRegistry.from_targets((target,))
    result = find_crossings(request, registry, model=MODEL, ephemeris=ephemeris)
    events = [e for e in result.events if e.validity is not Validity.INVALID]
    assert len(events) == 1
    event = events[0]
    assert event.b_min_au == pytest.approx(0.02, rel=0.05)

    uncertainty = crossing_uncertainty(
        event=event,
        target=target,
        observer=OBSERVER,
        ephemeris=ephemeris,
        model=MODEL,
        seed=17,
        count=32,
        window_days=40.0,
        refine_tolerance_s=3600.0,
    )
    assert uncertainty.method is UncertaintyMethod.PROPAGATED
    assert uncertainty.sample_count == 32
    assert (
        uncertainty.b_min_lower_au
        <= uncertainty.b_min_median_au
        <= uncertainty.b_min_upper_au
    )
    # The 100 arcsec axis tilt at s ~ 5 AU perturbs b by ~2.4e-3 AU.
    assert uncertainty.b_min_median_au == pytest.approx(0.02, rel=0.2)
    assert 5e-4 < uncertainty.b_min_sigma_au < 1e-2
    assert uncertainty.t_ca_sigma_days > 0.1
    assert (
        uncertainty.t_ca_lower_tdb_jd
        <= uncertainty.t_ca_median_tdb_jd
        <= uncertainty.t_ca_upper_tdb_jd
    )
    assert uncertainty.v_perp_sigma_km_s >= 0.0
    assert uncertainty.side_nominal is BeamSide.TARGET
    assert uncertainty.side_consistency_fraction == 1.0
    assert len(uncertainty.b_min_samples_au) == 32
    assert uncertainty.window_edge_count == 0
    assert uncertainty.validity is Validity.VALID

    again = crossing_uncertainty(
        event=event,
        target=target,
        observer=OBSERVER,
        ephemeris=ephemeris,
        model=MODEL,
        seed=17,
        count=32,
        window_days=40.0,
        refine_tolerance_s=3600.0,
    )
    assert again.b_min_samples_au == uncertainty.b_min_samples_au


def test_crossing_uncertainty_flags_window_edges() -> None:
    from sglseti.crossings import find_crossings

    target, ephemeris, request = crossing_scenario()
    registry = TargetRegistry.from_targets((target,))
    result = find_crossings(request, registry, model=MODEL, ephemeris=ephemeris)
    event = result.events[0]
    uncertainty = crossing_uncertainty(
        event=event,
        target=target,
        observer=OBSERVER,
        ephemeris=ephemeris,
        model=MODEL,
        seed=17,
        count=8,
        window_days=0.05,
        refine_tolerance_s=3600.0,
    )
    assert uncertainty.window_edge_count == 8
    assert uncertainty.validity is Validity.DEGRADED
    assert any(
        w.startswith(WARN_MINIMUM_AT_WINDOW_EDGE) for w in uncertainty.warnings
    )


def test_crossing_uncertainty_rejects_mismatched_target() -> None:
    from sglseti.crossings import find_crossings

    target, ephemeris, request = crossing_scenario()
    registry = TargetRegistry.from_targets((target,))
    result = find_crossings(request, registry, model=MODEL, ephemeris=ephemeris)
    other = make_target(parameter_provenance=provenance(ra_deg=(1.0, "mas")))
    other = Target(
        target_id="someone-else",
        display_name=other.display_name,
        endpoint_kind=other.endpoint_kind,
        astrometry=other.astrometry,
        parameter_provenance=other.parameter_provenance,
    )
    with pytest.raises(GenerationError, match="belongs to target"):
        crossing_uncertainty(
            event=result.events[0],
            target=other,
            observer=OBSERVER,
            ephemeris=ephemeris,
            model=MODEL,
            seed=1,
        )


# ---------------------------------------------------------------------------
# Observation-interval impact minimization
# ---------------------------------------------------------------------------


def test_minimize_impact_parameter_interior_minimum() -> None:
    target, ephemeris, _ = crossing_scenario()
    interval = ObservationInterval(
        interval_id="exp-1", start=T_O + 40.0, stop=T_O + 60.0
    )
    sample = minimize_impact_parameter(
        target=target,
        interval=interval,
        link_direction=LinkDirection.INBOUND,
        observer=OBSERVER,
        z_au=1000.0,
        ephemeris=ephemeris,
        model=MODEL,
    )
    assert sample.b_au == pytest.approx(0.02, rel=0.01)
    assert not any(w.startswith("minimum_at_interval") for w in sample.warnings)


def test_minimize_impact_parameter_boundary_minimum() -> None:
    target, ephemeris, _ = crossing_scenario()
    interval = ObservationInterval(interval_id="exp-2", start=T_O, stop=T_O + 20.0)
    sample = minimize_impact_parameter(
        target=target,
        interval=interval,
        link_direction=LinkDirection.INBOUND,
        observer=OBSERVER,
        z_au=1000.0,
        ephemeris=ephemeris,
        model=MODEL,
    )
    # b decreases toward the stop; the boundary minimum is informational.
    expected = math.hypot(0.05 - 0.001 * 20.0, 0.02)
    assert sample.b_au == pytest.approx(expected, rel=0.02)
    assert "minimum_at_interval_stop" in sample.warnings
    assert sample.validity is not Validity.INVALID
