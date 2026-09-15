"""Observation intervals and the continuous/adaptive locus API (§3.1-§3.2)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris, MovingEphemeris

from sglseti.geometry import Tusay2022Eq57V1, compute_relay_solution
from sglseti.locus import (
    WARN_ADAPTIVE_BUDGET,
    adaptive_locus,
    covered_z_intervals,
    evaluate_locus,
    interval_states,
    swept_locus,
)
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    ObservationInterval,
    Observer,
    RelayRange,
    Role,
    Target,
)

MODEL = Tusay2022Eq57V1()
T_O = Time("2021-11-06T00:00:00", scale="utc")
EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
OBSERVER = Observer.earth_center()
RANGE = RelayRange(550.0, 25000.0)


def make_target(*, pm_dec: float = -50.0, d_au: float = 200_000.0) -> Target:
    return Target(
        target_id="unit-test",
        display_name="Unit Test Star",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=100.0,
            pm_dec_mas_per_yr=pm_dec,
            reference_epoch_jyear=2000.0,
            reference_epoch_scale="tdb",
            source="unit test values",
            distance_pc=d_au / AU_PER_PC,
            radial_velocity_km_s=0.0,
        ),
    )


#: Barnard-scale proper motion: the rx-role catalog epoch shifts by 2z/c,
#: so a fast target bends the locus measurably away from a great circle.
CURVED_TARGET = make_target(pm_dec=10362.394, d_au=1.83 * AU_PER_PC)


def common(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        target=make_target(),
        role=Role.ANTIPODE,
        observation_time=T_O,
        observer=OBSERVER,
        ephemeris=EPHEMERIS,
        model=MODEL,
    )
    base.update(overrides)
    return base


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    return float(
        SkyCoord(ra1 * u.deg, dec1 * u.deg)
        .separation(SkyCoord(ra2 * u.deg, dec2 * u.deg))
        .to_value(u.arcsec)
    )


# ---------------------------------------------------------------------------
# ObservationInterval
# ---------------------------------------------------------------------------


def test_observation_interval_basics() -> None:
    interval = ObservationInterval(
        interval_id="obs-1",
        start=T_O,
        stop=T_O + 1.0 / 24.0,
        metadata={"archive": "demo"},
    )
    assert interval.duration_s == pytest.approx(3600.0)
    assert float((interval.midpoint - T_O).sec) == pytest.approx(1800.0)
    start, midpoint, stop = interval.representative_times()
    assert start is interval.start and stop is interval.stop
    assert interval.sample_times() == interval.representative_times()


def test_observation_interval_subintegration_grid() -> None:
    interval = ObservationInterval(
        interval_id="obs-2",
        start=T_O,
        stop=T_O + 1.0 / 24.0,
        subintegration_cadence_s=1000.0,
    )
    times = interval.sample_times()
    # 0, 1000, 2000, 3000 s from start, plus the stop time.
    assert len(times) == 5
    assert float((times[-1] - T_O).sec) == pytest.approx(3600.0)
    seconds = [float((time - T_O).sec) for time in times[:-1]]
    assert seconds == pytest.approx([0.0, 1000.0, 2000.0, 3000.0])


def test_observation_interval_validation() -> None:
    with pytest.raises(ValueError, match="start must precede stop"):
        ObservationInterval(interval_id="bad", start=T_O, stop=T_O)
    with pytest.raises(ValueError, match="must not exceed the interval duration"):
        ObservationInterval(
            interval_id="bad",
            start=T_O,
            stop=T_O + 1.0 / 24.0,
            subintegration_cadence_s=7200.0,
        )
    with pytest.raises(ValueError, match="interval_id"):
        ObservationInterval(interval_id="has space", start=T_O, stop=T_O + 1.0)


# ---------------------------------------------------------------------------
# Continuous evaluation
# ---------------------------------------------------------------------------


def test_evaluate_locus_matches_relay_solution() -> None:
    point = evaluate_locus(z_au=1000.0, **common())
    solution = compute_relay_solution(
        target=make_target(),
        observation_time=T_O,
        z_au=1000.0,
        role=Role.ANTIPODE,
        observer=OBSERVER,
        ephemeris=EPHEMERIS,
        model=MODEL,
    )
    assert point.icrs_ra_deg == solution.los_icrs_ra_deg
    assert point.icrs_dec_deg == solution.los_icrs_dec_deg
    assert point.q_per_au == pytest.approx(1e-3)
    assert point.validity is solution.direction.validity


# ---------------------------------------------------------------------------
# Adaptive sampling
# ---------------------------------------------------------------------------


def _max_deviation_from_polyline(locus: Any, dense: list[Any]) -> float:
    """Largest angular distance from dense reference points to the polyline."""
    from sglseti.locus import _point_polyline_arcsec, _point_vec

    vectors = [_point_vec(point) for point in locus.points]
    return max(_point_polyline_arcsec(_point_vec(point), vectors) for point in dense)


def test_adaptive_locus_structure() -> None:
    locus = adaptive_locus(relay_range=RANGE, tolerance_arcsec=1.0, **common())
    z_values = [point.z_au for point in locus.points]
    assert z_values == sorted(z_values)
    assert locus.points[0].z_au == RANGE.z_min_au
    assert locus.points[-1].z_au == RANGE.z_max_au
    assert locus.boundary_points == (locus.points[0], locus.points[-1])
    assert locus.model_id == MODEL.model_id
    assert locus.ephemeris_id == EPHEMERIS.ephemeris_id
    # The antipode locus is exactly a great-circle arc (the catalog
    # direction does not depend on z), so two points suffice.
    assert len(locus.points) == 2


@pytest.mark.parametrize("tolerance", [1.0, 0.1])
def test_adaptive_locus_meets_tolerance_against_dense_reference(
    tolerance: float,
) -> None:
    kwargs = common(target=CURVED_TARGET, role=Role.RX)
    locus = adaptive_locus(relay_range=RANGE, tolerance_arcsec=tolerance, **kwargs)
    assert not locus.warnings
    assert locus.achieved_deviation_arcsec <= 0.5 * tolerance
    q_grid = np.linspace(1.0 / RANGE.z_max_au, 1.0 / RANGE.z_min_au, 400)
    dense = [evaluate_locus(z_au=1.0 / q, **kwargs) for q in q_grid]
    assert _max_deviation_from_polyline(locus, dense) <= tolerance


def test_adaptive_locus_point_count_scales_with_tolerance() -> None:
    kwargs = common(target=CURVED_TARGET, role=Role.RX)
    loose = adaptive_locus(relay_range=RANGE, tolerance_arcsec=5.0, **kwargs)
    tight = adaptive_locus(relay_range=RANGE, tolerance_arcsec=0.05, **kwargs)
    assert len(tight.points) > len(loose.points) >= 2


def test_adaptive_budget_exhaustion_warns() -> None:
    kwargs = common(target=CURVED_TARGET, role=Role.RX)
    locus = adaptive_locus(relay_range=RANGE, tolerance_arcsec=0.001, max_points=3, **kwargs)
    assert WARN_ADAPTIVE_BUDGET in locus.warnings
    assert len(locus.points) <= 3


def test_adaptive_locus_rejects_bad_tolerance() -> None:
    with pytest.raises(ValueError, match="tolerance_arcsec"):
        adaptive_locus(relay_range=RANGE, tolerance_arcsec=0.0, **common())


# ---------------------------------------------------------------------------
# Swept locus
# ---------------------------------------------------------------------------


def test_swept_locus_envelope_contains_instantaneous_loci() -> None:
    ephemeris = MovingEphemeris((0.0, 0.017, 0.0), base_time=T_O)
    interval = ObservationInterval(interval_id="sweep-1", start=T_O, stop=T_O + 2.0)
    kwargs = common(ephemeris=ephemeris)
    del kwargs["observation_time"]
    swept = swept_locus(interval=interval, relay_range=RANGE, tolerance_arcsec=1.0, **kwargs)
    assert len(swept.loci) >= 3  # ~13 arcsec of drift forces refinement
    assert swept.envelope_pad_arcsec == pytest.approx(2.0)
    assert not swept.warnings

    from sglseti.locus import _point_polyline_arcsec, _point_vec

    union_vectors = [[_point_vec(point) for point in locus.points] for locus in swept.loci]
    for fraction in np.linspace(0.0, 1.0, 15):
        time = interval.start + fraction * (interval.stop - interval.start)
        for q in np.linspace(1.0 / RANGE.z_max_au, 1.0 / RANGE.z_min_au, 25):
            point = evaluate_locus(z_au=1.0 / q, observation_time=time, **kwargs)
            distance = min(
                _point_polyline_arcsec(_point_vec(point), vectors) for vectors in union_vectors
            )
            assert distance <= swept.envelope_pad_arcsec


def test_swept_locus_static_ephemeris_needs_no_refinement() -> None:
    interval = ObservationInterval(interval_id="sweep-2", start=T_O, stop=T_O + 2.0)
    kwargs = common()
    del kwargs["observation_time"]
    swept = swept_locus(interval=interval, relay_range=RANGE, tolerance_arcsec=1.0, **kwargs)
    # A static fake ephemeris means zero drift: boundary polylines only,
    # verified by one midpoint probe.
    assert len(swept.loci) == 2
    assert swept.interval_id == "sweep-2"


# ---------------------------------------------------------------------------
# Covered z intervals
# ---------------------------------------------------------------------------


def _cap_contains(center_ra: float, center_dec: float, radius_arcsec: float) -> Any:
    def contains(ra_deg: float, dec_deg: float) -> bool:
        return separation_arcsec(center_ra, center_dec, ra_deg, dec_deg) < radius_arcsec

    return contains


def test_covered_z_intervals_brackets_a_cap() -> None:
    kwargs = common()
    center = evaluate_locus(z_au=2000.0, **kwargs)
    radius = 30.0
    tolerance = 0.5
    intervals = covered_z_intervals(
        relay_range=RANGE,
        contains=_cap_contains(center.icrs_ra_deg, center.icrs_dec_deg, radius),
        tolerance_arcsec=tolerance,
        seed_step_arcsec=15.0,
        **kwargs,
    )
    assert len(intervals) == 1
    interval = intervals[0]
    assert interval.z_min_au < 2000.0 < interval.z_max_au
    # Endpoints are verified covered and sit within the refinement
    # tolerance of the cap boundary.
    for z in (interval.z_min_au, interval.z_max_au):
        point = evaluate_locus(z_au=z, **kwargs)
        separation = separation_arcsec(
            center.icrs_ra_deg, center.icrs_dec_deg, point.icrs_ra_deg, point.icrs_dec_deg
        )
        assert separation < radius
        assert separation > radius - 2.0 * tolerance


def test_covered_z_intervals_full_and_empty() -> None:
    kwargs = common()
    everything = covered_z_intervals(
        relay_range=RANGE,
        contains=lambda ra, dec: True,
        tolerance_arcsec=1.0,
        seed_step_arcsec=60.0,
        **kwargs,
    )
    assert len(everything) == 1
    assert everything[0].z_min_au == RANGE.z_min_au
    assert everything[0].z_max_au == RANGE.z_max_au
    nothing = covered_z_intervals(
        relay_range=RANGE,
        contains=lambda ra, dec: False,
        tolerance_arcsec=1.0,
        seed_step_arcsec=60.0,
        **kwargs,
    )
    assert nothing == ()


# ---------------------------------------------------------------------------
# Interval states
# ---------------------------------------------------------------------------


def test_interval_states_at_representative_times() -> None:
    interval = ObservationInterval(interval_id="obs-3", start=T_O, stop=T_O + 0.5)
    kwargs = common()
    del kwargs["observation_time"]
    states = interval_states(interval=interval, z_au=1000.0, **kwargs)
    assert len(states) == 3  # start, midpoint, stop
    assert states[0].interval_id == "obs-3"
    for state in states:
        assert math.isfinite(state.icrs_ra_deg)
        assert math.isfinite(state.rate_ra_cosdec_arcsec_per_hr)
        assert math.isfinite(state.rate_dec_arcsec_per_hr)
        assert state.z_au == 1000.0


def test_interval_states_follow_subintegration_cadence() -> None:
    interval = ObservationInterval(
        interval_id="obs-4",
        start=T_O,
        stop=T_O + 1.0 / 24.0,
        subintegration_cadence_s=1200.0,
    )
    kwargs = common()
    del kwargs["observation_time"]
    states = interval_states(interval=interval, z_au=1000.0, **kwargs)
    assert len(states) == len(interval.sample_times()) == 4
