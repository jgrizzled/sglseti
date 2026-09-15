"""Pointing footprints must cover the relay-distance intervals they claim.

Regression for review finding 2 (notes/review.md): range sampling partitions
reciprocal distance but used to evaluate geometry only at each segment
midpoint, so a pointing's center and radius came from representative
coordinates alone and could undercover the represented [z_near, z_far]
intervals. Samples now carry their interval bounds and the geometric ICRS
coordinates at both boundaries, and the planner's zone radius must contain
every such boundary.

The adversarial fixture mirrors the review's numerical check: reciprocal
sampling at a 15 arcsec step against a 10 arcsec usable field radius, with
no assumed half-width so nothing masks an undersized track extent.
"""

from __future__ import annotations

import math

import pytest
from support import build_small_result, separation_arcsec

from sglseti.models import (
    FieldOfView,
    OutputFormat,
    RelayRange,
    SamplingKind,
    SamplingSpec,
    Validity,
)

COVERAGE_TOLERANCE_ARCSEC = 1e-6


@pytest.fixture(scope="module")
def planned():
    return build_small_result(
        planned=True,
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.RECIPROCAL_STEP, step_arcsec=15.0),
        fov=FieldOfView(radius_arcsec=10.0, exposure_s=None),
        assumed_half_width_arcsec=None,
        output_formats=(OutputFormat.JSON,),
    )


def _grouped_samples(planned, pointing):
    """The samples a pointing was built from (representative-epoch corridor)."""
    samples = [
        s
        for s in planned.samples
        if s.sample_id in pointing.sample_ids
        and s.role is pointing.role
        and s.target_id == pointing.target_id
        and s.observation_time_utc == pointing.representative_time_utc
    ]
    assert len(samples) == len(pointing.sample_ids)
    return samples


def test_samples_carry_interval_bounds_and_boundary_coordinates(planned) -> None:
    for sample in planned.samples:
        assert sample.z_near_au is not None and sample.z_far_au is not None
        assert sample.z_near_au <= sample.z_au <= sample.z_far_au
        assert sample.q_lo_per_au == pytest.approx(1.0 / sample.z_far_au)
        assert sample.q_hi_per_au == pytest.approx(1.0 / sample.z_near_au)
        points = sample.coverage_radec()
        assert len(points) == 3  # representative + near + far
        assert all(math.isfinite(ra) and math.isfinite(dec) for ra, dec in points)


def test_adjacent_segments_share_boundary_coordinates(planned) -> None:
    for corridor in planned.corridors:
        ordered = corridor.samples
        assert ordered[0].z_near_au == corridor.z_min_au
        assert ordered[-1].z_far_au == corridor.z_max_au
        for previous, following in zip(ordered[:-1], ordered[1:], strict=False):
            assert previous.z_far_au == following.z_near_au
            # Same epoch and same z: the shared boundary evaluates to the
            # exact same coordinate on both sides.
            assert previous.far_icrs_ra_deg == following.near_icrs_ra_deg
            assert previous.far_icrs_dec_deg == following.near_icrs_dec_deg


def test_every_interval_boundary_lies_within_its_pointing_radius(planned) -> None:
    assert planned.pointings
    for pointing in planned.pointings:
        for sample in _grouped_samples(planned, pointing):
            for ra, dec in sample.coverage_radec():
                distance = separation_arcsec(
                    pointing.center_icrs_ra_deg, pointing.center_icrs_dec_deg, ra, dec
                )
                assert distance <= pointing.radius_arcsec + COVERAGE_TOLERANCE_ARCSEC


def test_pointings_state_their_covered_relay_interval(planned) -> None:
    for pointing in planned.pointings:
        samples = _grouped_samples(planned, pointing)
        assert pointing.z_near_au == min(s.z_near_au for s in samples)
        assert pointing.z_far_au == max(s.z_far_au for s in samples)
    # Per role and window, the claimed intervals tile the full requested
    # range with no gaps between adjacent pointings.
    by_window = {}
    for pointing in planned.pointings:
        key = (pointing.role, pointing.window_start_utc)
        by_window.setdefault(key, []).append(pointing)
    for pointings in by_window.values():
        ordered = sorted(pointings, key=lambda p: p.z_near_au)
        assert ordered[0].z_near_au == 550.0
        assert ordered[-1].z_far_au == 2500.0
        for previous, following in zip(ordered[:-1], ordered[1:], strict=False):
            assert previous.z_far_au == following.z_near_au


def test_explicit_point_segments_have_coincident_boundaries() -> None:
    result = build_small_result(
        sampling=SamplingSpec(kind=SamplingKind.EXPLICIT, distances_au=(600.0, 1200.0)),
        output_formats=(OutputFormat.JSON,),
        assumed_half_width_arcsec=None,
    )
    for sample in result.samples:
        assert sample.z_near_au == sample.z_far_au == sample.z_au
        assert sample.near_icrs_ra_deg == sample.icrs_ra_deg
        assert sample.far_icrs_ra_deg == sample.icrs_ra_deg


def test_invalid_rows_keep_interval_bounds_but_nan_boundaries() -> None:
    from support import FakeEphemeris

    limited = FakeEphemeris(
        (0.004, -0.002, 0.001),
        (0.558, -0.744, -0.323),
        coverage_jd=(2459000.0, 2459600.0),  # excludes epoch e2
    )
    result = build_small_result(ephemeris=limited)
    invalid = [s for s in result.samples if s.validity is Validity.INVALID]
    assert invalid
    for sample in invalid:
        assert sample.z_near_au is not None and sample.z_far_au is not None
        assert math.isnan(sample.near_icrs_ra_deg)
        assert math.isnan(sample.far_icrs_ra_deg)
        # NaN boundaries drop out; only the (NaN) representative remains.
        assert len(sample.coverage_radec()) == 1
