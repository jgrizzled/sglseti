"""End-to-end commensal planning (UC3) through the Python API.

A small real night: Barnard's Star loci over a Kitt Peak night grid, rates
and constraints on, then stateless planning on top of the generated result.
The night is chosen so the line of sight rises during the grid: early epochs
fail the altitude constraint and later ones pass, exercising real window
construction.
"""

from __future__ import annotations

import dataclasses

import pytest
from astropy.time import Time
from support import EXAMPLES_DIR

from sglseti.errors import PlanningError
from sglseti.generate import generate_loci, materialize_epochs
from sglseti.models import (
    CoordinateProduct,
    FieldOfView,
    GeometryRequest,
    ObservabilityConstraints,
    Observer,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    TimeGrid,
)
from sglseti.planning import plan_commensal
from sglseti.targets import load_target_registry


@pytest.fixture(scope="module")
def context():
    registry = load_target_registry(EXAMPLES_DIR / "targets.yaml")
    request = GeometryRequest(
        target_ids=("barnard",),
        roles=(Role.RX, Role.TX),
        time=TimeGrid(
            start=Time("2021-11-06T02:00:00", scale="utc"),
            stop=Time("2021-11-06T08:00:00", scale="utc"),
            cadence_s=3600.0,
        ),
        observer=Observer.from_geodetic("kitt-peak", -111.6003, 31.9583, 2096.0),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=4),
        model_id="tusay2022_eq5_7_v1",
        coordinate_products=(CoordinateProduct.ICRS,),
        include_rates=True,
        assumed_half_width_arcsec=30.0,
        observability=ObservabilityConstraints(
            min_target_altitude_deg=25.0,
            max_sun_altitude_deg=-12.0,
            min_moon_separation_deg=20.0,
        ),
        fov=FieldOfView(radius_arcsec=200.0, exposure_s=300.0),
    )
    generated = generate_loci(request, registry)
    planned = plan_commensal(generated, registry)
    return registry, request, generated, planned


def test_visibility_covers_every_role_epoch(context) -> None:
    _, request, _, planned = context
    epochs = materialize_epochs(request.time)
    assert len(epochs) == 7
    assert len(planned.visibility) == 2 * 7
    keys = {(v.role, v.epoch_id) for v in planned.visibility}
    assert len(keys) == 14


def test_windows_reflect_rising_line_of_sight(context) -> None:
    _, _, _, planned = context
    rx_visibility = [v for v in planned.visibility if v.role is Role.RX]
    passing = [v.constraints_passed for v in rx_visibility]
    # The LOS rises through the night: fails early, passes late.
    assert passing[0] is False
    assert passing[-1] is True
    assert any(passing)


def test_pointings_are_candidate_zones_with_windows(context) -> None:
    _, request, _, planned = context
    assert planned.pointings
    grid_times = {str(e.time.utc.isot) for e in materialize_epochs(request.time)}
    for pointing in planned.pointings:
        assert pointing.calculation_id == planned.calculation_id
        assert pointing.usable_radius_arcsec == 200.0
        assert pointing.window_start_utc in grid_times
        assert pointing.window_stop_utc in grid_times
        assert pointing.representative_time_utc in grid_times
        # Conservative radius decomposes into its labeled components.
        assert pointing.radius_arcsec == pytest.approx(
            pointing.track_extent_arcsec
            + (pointing.assumed_half_width_arcsec or 0.0)
            + pointing.motion_padding_arcsec
            + pointing.window_drift_arcsec,
            abs=1e-9,
        )
        assert pointing.window_drift_arcsec >= 0.0
        assert pointing.assumed_half_width_arcsec == 30.0
        assert pointing.propagated_half_width_arcsec is None
        assert pointing.motion_padding_arcsec > 0.0  # exposure_s configured
        assert pointing.sample_ids


def test_pointing_samples_come_from_representative_corridor(context) -> None:
    _, _, _, planned = context
    corridors = {
        (c.target_id, c.role, c.epoch_id): {s.sample_id for s in c.samples}
        for c in planned.corridors
    }
    for pointing in planned.pointings:
        window_epochs = [
            (target, role, epoch_id)
            for (target, role, epoch_id) in corridors
            if target == pointing.target_id and role == pointing.role
        ]
        assert any(set(pointing.sample_ids) <= corridors[key] for key in window_epochs)


def test_planning_is_stateless_and_pure(context) -> None:
    registry, _, generated, planned = context
    # The generated input is untouched.
    assert generated.pointings == ()
    assert generated.visibility == ()
    # Re-planning from the same inputs reproduces the plan exactly.
    again = plan_commensal(generated, registry)
    assert again.pointings == planned.pointings
    assert again.visibility == planned.visibility
    assert again.warnings == planned.warnings


def test_ordering_is_stable_priority_then_epoch(context) -> None:
    _, _, _, planned = context
    # One target: request role order first (rx before tx) …
    roles = [p.role for p in planned.pointings]
    assert roles == sorted(roles, key=lambda r: r is Role.TX)
    # … then window (epoch) order within each role.
    for role in (Role.RX, Role.TX):
        starts = [p.window_start_utc for p in planned.pointings if p.role is role]
        assert starts == sorted(starts)


def test_planning_requires_observability_and_fov(context) -> None:
    registry, request, generated, _ = context
    without_observability = dataclasses.replace(
        generated,
        request=dataclasses.replace(request, observability=None),
    )
    with pytest.raises(PlanningError, match="observability"):
        plan_commensal(without_observability, registry)
    without_fov = dataclasses.replace(
        generated,
        request=dataclasses.replace(request, fov=None),
    )
    with pytest.raises(PlanningError, match="fov"):
        plan_commensal(without_fov, registry)


def test_no_schedule_language(context) -> None:
    _, _, _, planned = context
    for warning in planned.warnings:
        assert "schedule" not in warning
