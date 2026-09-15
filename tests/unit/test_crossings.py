"""Analytic checks of the sun_star_axis_v1 crossing search.

A fake circular one-AU orbit in the ICRS xy-plane makes every expectation
closed-form: a target on the +x axis is crossed exactly twice per period
(once per side) with b_min ~ 0, a target at declination beta has
b_min = sin(beta), the transverse speed is the orbital speed, and an
assumed beam radius R yields a window duration 2*asin(R)/omega.
"""

from __future__ import annotations

import math

import pytest
from astropy.time import Time

from sglseti.crossings import (
    WARN_MINIMUM_AT_INTERVAL_START,
    find_crossings,
    impact_parameter,
)
from sglseti.errors import GenerationError
from sglseti.models import (
    AstrometricState,
    BeamSide,
    CrossingsRequest,
    EndpointKind,
    LinkDirection,
    Observer,
    Role,
    Target,
    TimeInterval,
    Validity,
)
from sglseti.targets import TargetRegistry

PERIOD_DAYS = 365.25
OMEGA = 2.0 * math.pi / PERIOD_DAYS  # rad / day
#: TDB JD at which the fake Earth sits exactly on the +x axis.
JD0 = 2459580.5
KM_PER_AU = 149_597_870.700
AU_PER_PC = 648_000 / math.pi


class CircularOrbitEphemeris:
    """Sun at the barycenter; Earth on a circular 1 AU orbit in the xy-plane."""

    def __init__(self, coverage_jd: tuple[float, float] | None = None) -> None:
        self._coverage = coverage_jd

    @property
    def ephemeris_id(self) -> str:
        return "fake_circular_orbit"

    def _check(self, time: Time) -> None:
        if self._coverage is not None:
            from sglseti.errors import EphemerisCoverageError

            jd = float(time.tdb.jd)
            if not self._coverage[0] <= jd <= self._coverage[1]:
                raise EphemerisCoverageError(
                    f"epoch jd={jd} outside fake coverage {self._coverage}"
                )

    def sun_barycentric_au(self, time: Time) -> object:
        import numpy as np

        self._check(time)
        return np.zeros(3)

    def earth_barycentric_au(self, time: Time) -> object:
        import numpy as np

        self._check(time)
        theta = OMEGA * (float(time.tdb.jd) - JD0)
        return np.array([math.cos(theta), math.sin(theta), 0.0])

    def moon_barycentric_au(self, time: Time) -> object:
        import numpy as np

        earth = self.earth_barycentric_au(time)
        return np.asarray(earth) + np.array([0.00257, 0.0, 0.0])


def make_target(
    *,
    dec_deg: float = 0.0,
    pm_ra_cosdec: float = 0.0,
    distance_pc: float = 10.0,
    radial_velocity_km_s: float | None = 0.0,
) -> Target:
    return Target(
        target_id="axis-star",
        display_name="Axis Star",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=0.0,
            dec_deg=dec_deg,
            pm_ra_cosdec_mas_per_yr=pm_ra_cosdec,
            pm_dec_mas_per_yr=0.0,
            reference_epoch_jyear=2022.0,
            reference_epoch_scale="tdb",
            source="crossing test values",
            distance_pc=distance_pc,
            radial_velocity_km_s=radial_velocity_km_s,
        ),
        flags=("missing_radial_velocity",) if radial_velocity_km_s is None else (),
    )


def tdb(jd: float) -> Time:
    return Time(jd, format="jd", scale="tdb")


def make_request(
    *,
    # Default interval phases: it opens while b is falling toward the
    # anti-target minimum and closes while b is rising after the
    # target-side minimum, so exactly two interior minima and no boundary
    # events exist.
    start_jd: float = JD0 + 120.0,
    span_days: float = 300.0,
    directions: tuple[LinkDirection, ...] = (LinkDirection.INBOUND,),
    beam_radii_au: tuple[float, ...] = (),
    report_max_b_au: float | None = None,
    **overrides: object,
) -> CrossingsRequest:
    values: dict[str, object] = dict(
        target_ids=("axis-star",),
        link_directions=directions,
        intervals=(
            TimeInterval(
                interval_id="i1",
                start=tdb(start_jd),
                stop=tdb(start_jd + span_days),
            ),
        ),
        observer=Observer.earth_center(),
        relay_distance_au=800.0,
        model_id="tusay2022_eq5_7_v1",
        beam_radii_au=beam_radii_au,
        report_max_b_au=report_max_b_au,
    )
    values.update(overrides)
    return CrossingsRequest(**values)  # type: ignore[arg-type]


def run(request: CrossingsRequest, target: Target, **kwargs: object):
    registry = TargetRegistry.from_targets((target,))
    return find_crossings(request, registry, ephemeris=CircularOrbitEphemeris(), **kwargs)


class TestInPlaneTarget:
    def test_two_crossings_per_period_with_analytic_geometry(self) -> None:
        result = run(make_request(beam_radii_au=(0.05, 0.2)), make_target())
        events = result.events
        assert len(events) == 2
        anti, target_side = events
        assert anti.side is BeamSide.ANTI_TARGET
        assert target_side.side is BeamSide.TARGET
        assert [e.validity for e in events] == [Validity.VALID, Validity.VALID]
        assert anti.t_ca_tdb_jd == pytest.approx(JD0 + PERIOD_DAYS / 2, abs=0.002)
        assert target_side.t_ca_tdb_jd == pytest.approx(JD0 + PERIOD_DAYS, abs=0.002)
        for event in events:
            assert event.b_min_au < 1e-4
            assert abs(abs(event.axis_distance_au) - 1.0) < 1e-6
            expected_v = OMEGA * KM_PER_AU / 86_400.0
            assert event.v_perp_km_s == pytest.approx(expected_v, rel=1e-3)
            assert event.axis_icrs_ra_deg == pytest.approx(0.0, abs=1e-9)
            assert event.axis_icrs_dec_deg == pytest.approx(0.0, abs=1e-9)
            assert event.role is Role.ANTIPODE
            assert event.z_au == 800.0
            assert event.ephemeris_id == "fake_circular_orbit"
            # Both assumed radii produce windows, ascending radius order.
            assert [w.beam_radius_au for w in event.windows] == [0.05, 0.2]
            for window in event.windows:
                expected = 2.0 * math.asin(window.beam_radius_au) / OMEGA
                assert window.duration_days == pytest.approx(expected, rel=0.01)
                assert not window.truncated_ingress
                assert not window.truncated_egress
                assert window.egress_tdb_jd - window.ingress_tdb_jd == pytest.approx(
                    window.duration_days
                )

    def test_pointings_star_and_relay_are_antipodal(self) -> None:
        result = run(make_request(), make_target())
        target_side = result.events[1]
        # From the target side (+x, 1 AU), the star still lies at ~RA 0 and
        # the relay at 800 AU behind the Sun lies at ~RA 180.
        assert target_side.star_icrs_ra_deg == pytest.approx(0.0, abs=1e-3)
        assert math.cos(math.radians(target_side.relay_icrs_ra_deg)) == pytest.approx(
            -1.0, abs=1e-6
        )

    def test_deterministic_ids(self) -> None:
        first = run(make_request(), make_target())
        second = run(make_request(), make_target())
        assert first.crossings_id == second.crossings_id
        assert [e.event_id for e in first.events] == [e.event_id for e in second.events]
        assert len({e.event_id for e in first.events}) == len(first.events)

    def test_boundary_minimum_is_truncated_and_degraded(self) -> None:
        # The interval starts exactly at a target-side crossing: the first
        # event is a boundary minimum, degraded and flagged, its window
        # ingress truncated at the interval edge.
        result = run(
            make_request(start_jd=JD0, span_days=80.0, beam_radii_au=(0.2,)),
            make_target(),
        )
        (event,) = result.events
        assert event.t_ca_tdb_jd == pytest.approx(JD0)
        assert event.validity is Validity.DEGRADED
        assert WARN_MINIMUM_AT_INTERVAL_START in event.warnings
        (window,) = event.windows
        assert window.truncated_ingress
        assert not window.truncated_egress
        assert window.ingress_tdb_jd == pytest.approx(JD0)
        assert window.duration_days == pytest.approx(math.asin(0.2) / OMEGA, rel=0.01)


class TestInclinedTarget:
    def test_minimum_impact_parameter_is_sine_of_latitude(self) -> None:
        result = run(make_request(), make_target(dec_deg=30.0))
        assert len(result.events) == 2
        for event in result.events:
            assert event.b_min_au == pytest.approx(0.5, abs=1e-3)

    def test_report_max_filters_events(self) -> None:
        result = run(make_request(report_max_b_au=0.3), make_target(dec_deg=30.0))
        assert result.events == ()


class TestLinkDirections:
    def test_outbound_axis_uses_tx_epoch(self) -> None:
        # 1000 mas/yr of proper motion over the tx re-indexing 2d/c
        # (~32.6 yr at 5 pc) separates the outbound axis from the inbound
        # (apparent) axis by tens of arcseconds.
        target = make_target(pm_ra_cosdec=1000.0, distance_pc=5.0)
        result = run(
            make_request(directions=(LinkDirection.INBOUND, LinkDirection.OUTBOUND)),
            target,
        )
        inbound = [e for e in result.events if e.link_direction is LinkDirection.INBOUND]
        outbound = [e for e in result.events if e.link_direction is LinkDirection.OUTBOUND]
        assert len(inbound) == 2 and len(outbound) == 2
        assert all(e.role is Role.ANTIPODE for e in inbound)
        assert all(e.role is Role.TX for e in outbound)
        two_d_over_c_yr = 2.0 * 5.0 * AU_PER_PC / 63_241.077  # au / (au/yr)
        expected_offset_deg = 1000.0 / 1000.0 / 3600.0 * two_d_over_c_yr
        offset = outbound[0].axis_icrs_ra_deg - inbound[0].axis_icrs_ra_deg
        assert offset == pytest.approx(expected_offset_deg, rel=0.05)
        assert (
            outbound[0].catalog_direction_epoch_tdb_jd > inbound[0].catalog_direction_epoch_tdb_jd
        )


class TestQualityAndFailure:
    def test_missing_radial_velocity_degrades(self) -> None:
        result = run(make_request(), make_target(radial_velocity_km_s=None))
        assert len(result.events) == 2
        for event in result.events:
            assert event.validity is Validity.DEGRADED
            assert "missing_radial_velocity" in event.warnings
        assert "degraded_event_count:2" in result.warnings

    def test_uncertainty_never_silently_absent(self) -> None:
        result = run(make_request(), make_target())
        assert "uncertainty_not_propagated" in result.warnings

    def test_coverage_failure_yields_invalid_row(self) -> None:
        request = make_request()
        registry = TargetRegistry.from_targets((make_target(),))
        ephemeris = CircularOrbitEphemeris(coverage_jd=(JD0, JD0 + 100.0))
        result = find_crossings(request, registry, ephemeris=ephemeris)
        (event,) = result.events
        assert event.validity is Validity.INVALID
        assert math.isnan(event.b_min_au)
        assert event.side is None
        assert event.windows == ()
        assert any("ephemeris_out_of_coverage" in w for w in event.warnings)
        assert "invalid_event_count:1" in result.warnings

    def test_strict_mode_raises_on_coverage_failure(self) -> None:
        request = make_request()
        registry = TargetRegistry.from_targets((make_target(),))
        ephemeris = CircularOrbitEphemeris(coverage_jd=(JD0, JD0 + 100.0))
        with pytest.raises(GenerationError, match="strict mode"):
            find_crossings(request, registry, ephemeris=ephemeris, strict=True)

    def test_unknown_target_rejected(self) -> None:
        registry = TargetRegistry.from_targets((make_target(),))
        request = make_request()
        request = CrossingsRequest(
            target_ids=("nope",),
            link_directions=request.link_directions,
            intervals=request.intervals,
            observer=request.observer,
            relay_distance_au=request.relay_distance_au,
            model_id=request.model_id,
        )
        with pytest.raises(GenerationError, match="unknown target"):
            find_crossings(request, registry, ephemeris=CircularOrbitEphemeris())


class TestImpactParameterPointApi:
    def test_values_at_known_phases(self) -> None:
        target = make_target()
        observer = Observer.earth_center()
        ephemeris = CircularOrbitEphemeris()
        on_axis = impact_parameter(
            target=target,
            time=tdb(JD0),
            link_direction=LinkDirection.INBOUND,
            observer=observer,
            z_au=800.0,
            ephemeris=ephemeris,
        )
        assert on_axis.b_au < 1e-9
        assert on_axis.side is BeamSide.TARGET
        assert on_axis.axis_distance_au == pytest.approx(1.0)
        quadrature = impact_parameter(
            target=target,
            time=tdb(JD0 + PERIOD_DAYS / 4),
            link_direction=LinkDirection.INBOUND,
            observer=observer,
            z_au=800.0,
            ephemeris=ephemeris,
        )
        assert quadrature.b_au == pytest.approx(1.0, abs=1e-9)
        assert quadrature.axis_distance_au == pytest.approx(0.0, abs=1e-9)
        assert quadrature.b_km == pytest.approx(KM_PER_AU, rel=1e-9)
        assert quadrature.validity is Validity.VALID

    def test_event_matches_point_api_at_closest_approach(self) -> None:
        result = run(make_request(), make_target())
        event = result.events[0]
        sample = impact_parameter(
            target=make_target(),
            time=tdb(event.t_ca_tdb_jd),
            link_direction=LinkDirection.INBOUND,
            observer=Observer.earth_center(),
            z_au=800.0,
            ephemeris=CircularOrbitEphemeris(),
        )
        assert sample.b_au == pytest.approx(event.b_min_au, abs=1e-9)
        assert sample.side is event.side
