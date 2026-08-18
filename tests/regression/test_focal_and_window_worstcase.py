"""Finite-source focal threshold and worst-case visibility/windows.

Regressions for review findings.

Finding 4: the universal 547.7576 AU focal constant is the ideal threshold
for a source at INFINITY; a source at finite distance ``d`` needs
``z_min = f_inf d / (d - f_inf)``. Samples below the finite-source
threshold are now degraded (not silently valid), and pointings built from
them carry ``below_solar_focal_minimum``.

Finding 5: visibility used to be judged only at the middle corridor
sample, and pointings were positioned at the window's representative epoch
with no allowance for drift across the advertised window. Visibility now
probes the corridor's angular extremes, and pointing radii include a
``window_drift_arcsec`` component bounding the group's motion over the
window's grid epochs.
"""

from __future__ import annotations

import pytest
from astropy.time import Time
from support import FakeEphemeris, build_small_result, make_locus_sample, separation_arcsec

from sglseti.geometry import (
    SOLAR_FOCAL_MIN_AU,
    WARN_BELOW_FOCAL,
    solar_focal_min_au,
)
from sglseti.models import (
    Epoch,
    ObservabilityConstraints,
    Observer,
    RelayRange,
    SamplingKind,
    SamplingSpec,
    Validity,
)
from sglseti.observability import visibility_sample


class TestFiniteSourceFocalThreshold:
    def test_review_reference_values(self) -> None:
        # The review's table (Turyshev & Toth finite-distance relation).
        assert solar_focal_min_au(277_939.964) == pytest.approx(
            548.839193, abs=1e-6
        )  # Alpha Centauri
        assert solar_focal_min_au(377_100.355) == pytest.approx(
            548.554357, abs=1e-6
        )  # Barnard's Star

    def test_below_threshold_samples_degrade_and_flag_pointings(self) -> None:
        # An entire relay range below the focal threshold: every sample is
        # degraded and every pointing carries the code.
        planned = build_small_result(
            planned=True,
            relay_range=RelayRange(480.0, 520.0),
            sampling=SamplingSpec(kind=SamplingKind.COUNT, count=3),
        )
        for sample in planned.samples:
            assert sample.z_au < SOLAR_FOCAL_MIN_AU
            assert WARN_BELOW_FOCAL in sample.warnings
            assert sample.validity is Validity.DEGRADED
            assert sample.is_operational  # degraded, not excluded
        assert planned.pointings
        for pointing in planned.pointings:
            assert WARN_BELOW_FOCAL in pointing.warnings


class TestWorstCaseVisibility:
    def test_probe_point_failure_fails_the_visibility_sample(self) -> None:
        # Representative near zenith passes; a probe far down the sky fails
        # the altitude constraint — the verdict must cover the probe.
        common = dict(
            epoch=Epoch(
                epoch_id="e1", time=Time("2021-11-06T00:00:00", scale="utc")
            ),
            observer=Observer.from_geodetic(
                "test-site", -111.6003, 31.9583, 2096.0
            ),
            ephemeris=FakeEphemeris(
                (0.004, -0.002, 0.001), (0.558, -0.744, -0.323)
            ),
            constraints=ObservabilityConstraints(
                min_target_altitude_deg=0.0,
                max_sun_altitude_deg=90.0,
                min_moon_separation_deg=0.0,
            ),
        )
        sample = make_locus_sample()
        baseline = visibility_sample(sample=sample, **common)
        assert baseline.constraints_passed is True
        probed = visibility_sample(
            sample=sample,
            probe_points=((sample.icrs_ra_deg, sample.icrs_dec_deg - 80.0),),
            **common,
        )
        assert probed.constraints_passed is False
        assert "target_below_min_altitude" in probed.failed_constraints
        # Reported values stay the representative's.
        assert probed.altitude_deg == baseline.altitude_deg


@pytest.fixture(scope="module")
def planned():
    # Two epochs four months apart under permissive constraints: one
    # window spanning both, so the pointing must cover the drift.
    return build_small_result(planned=True)


class TestWindowDrift:
    def test_pointings_report_positive_window_drift(self, planned) -> None:
        assert planned.pointings
        assert any(p.window_drift_arcsec > 0.0 for p in planned.pointings)
        for pointing in planned.pointings:
            assert pointing.window_drift_arcsec >= 0.0

    def test_radius_covers_the_group_at_every_window_epoch(self, planned) -> None:
        for pointing in planned.pointings:
            window_times = {
                v.time_utc
                for v in planned.visibility
                if v.role is pointing.role
                and pointing.window_start_utc <= v.time_utc <= pointing.window_stop_utc
            }
            assert window_times
            members = [
                s
                for s in planned.samples
                if s.sample_id in pointing.sample_ids
                and s.role is pointing.role
                and s.observation_time_utc in window_times
            ]
            # Same segments exist at every window epoch.
            assert len(members) == len(pointing.sample_ids) * len(window_times)
            for sample in members:
                for ra, dec in sample.coverage_radec():
                    assert (
                        separation_arcsec(
                            pointing.center_icrs_ra_deg,
                            pointing.center_icrs_dec_deg,
                            ra,
                            dec,
                        )
                        <= pointing.radius_arcsec + 1e-6
                    )
