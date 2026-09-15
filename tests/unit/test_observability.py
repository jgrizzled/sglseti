from __future__ import annotations

import math

import pytest
from astropy.time import Time, TimeDelta
from support import FakeEphemeris, make_locus_sample

from sglseti.errors import PlanningError
from sglseti.models import (
    Epoch,
    ObservabilityConstraints,
    Observer,
    Role,
    VisibilitySample,
)
from sglseti.observability import (
    FAIL_MOON_SEPARATION,
    FAIL_SUN_ALTITUDE,
    FAIL_TARGET_ALTITUDE,
    evaluate_constraints,
    find_windows,
    visibility_sample,
)

CONSTRAINTS = ObservabilityConstraints(
    min_target_altitude_deg=25.0,
    max_sun_altitude_deg=-12.0,
    min_moon_separation_deg=20.0,
)

SITE = Observer.from_geodetic("kitt-peak", -111.6003, 31.9583, 2096.0)
T0 = Time("2021-11-06T03:00:00", scale="utc")


def check(alt: float, sun: float, moon: float) -> tuple[bool, tuple[str, ...]]:
    return evaluate_constraints(
        altitude_deg=alt,
        sun_altitude_deg=sun,
        moon_separation_deg=moon,
        constraints=CONSTRAINTS,
    )


class TestConstraintBoundaries:
    def test_all_pass_inclusive_thresholds(self) -> None:
        # Values exactly at the thresholds pass.
        assert check(25.0, -12.0, 20.0) == (True, ())

    def test_target_altitude_boundary(self) -> None:
        passed, failed = check(24.999, -30.0, 90.0)
        assert not passed and failed == (FAIL_TARGET_ALTITUDE,)

    def test_sun_altitude_boundary(self) -> None:
        passed, failed = check(60.0, -11.999, 90.0)
        assert not passed and failed == (FAIL_SUN_ALTITUDE,)

    def test_moon_separation_boundary(self) -> None:
        passed, failed = check(60.0, -30.0, 19.999)
        assert not passed and failed == (FAIL_MOON_SEPARATION,)

    def test_multiple_failures_all_reported(self) -> None:
        passed, failed = check(0.0, 10.0, 1.0)
        assert not passed
        assert set(failed) == {
            FAIL_TARGET_ALTITUDE,
            FAIL_SUN_ALTITUDE,
            FAIL_MOON_SEPARATION,
        }


def make_grid(count: int) -> tuple[Epoch, ...]:
    return tuple(
        Epoch(epoch_id=f"grid-{i:06d}", time=T0 + TimeDelta(600 * i, format="sec"))
        for i in range(count)
    )


def vis(epoch: Epoch, passed: bool) -> VisibilitySample:
    return VisibilitySample(
        target_id="synth",
        role=Role.RX,
        epoch_id=epoch.epoch_id,
        time_utc=str(epoch.time.utc.isot),
        altitude_deg=50.0 if passed else 5.0,
        azimuth_deg=100.0,
        sun_altitude_deg=-30.0,
        moon_separation_deg=90.0,
        constraints_passed=passed,
        failed_constraints=() if passed else (FAIL_TARGET_ALTITUDE,),
    )


class TestWindows:
    def windows(self, pattern: list[bool]):
        epochs = make_grid(len(pattern))
        visibility = tuple(vis(e, p) for e, p in zip(epochs, pattern, strict=True))
        return find_windows(target_id="synth", role=Role.RX, epochs=epochs, visibility=visibility)

    def test_single_window_with_representative_midpoint(self) -> None:
        (window,) = self.windows([True, True, True, True, True])
        assert window.epoch_ids == tuple(f"grid-{i:06d}" for i in range(5))
        assert window.representative_epoch_id == "grid-000002"  # index len//2
        assert window.start_utc < window.representative_utc < window.stop_utc

    def test_multiple_disjoint_windows_all_returned(self) -> None:
        first, second = self.windows([True, True, False, True, True, True])
        assert first.epoch_ids == ("grid-000000", "grid-000001")
        assert first.representative_epoch_id == "grid-000001"
        assert second.epoch_ids == ("grid-000003", "grid-000004", "grid-000005")
        assert second.representative_epoch_id == "grid-000004"

    def test_never_visible_returns_no_windows(self) -> None:
        assert self.windows([False, False, False]) == ()

    def test_edges_and_singletons(self) -> None:
        windows = self.windows([True, False, True])
        assert len(windows) == 2
        assert all(len(w.epoch_ids) == 1 for w in windows)
        assert windows[0].start_utc == windows[0].stop_utc

    def test_misaligned_inputs_rejected(self) -> None:
        epochs = make_grid(3)
        with pytest.raises(PlanningError, match="misaligned"):
            find_windows(
                target_id="synth",
                role=Role.RX,
                epochs=epochs,
                visibility=(vis(epochs[0], True),),
            )


class TestVisibilitySample:
    def test_requires_site_observer(self) -> None:
        with pytest.raises(PlanningError, match="site observer"):
            visibility_sample(
                sample=make_locus_sample(),
                epoch=Epoch(epoch_id="e1", time=T0),
                observer=Observer.earth_center(),
                ephemeris=FakeEphemeris((0, 0, 0), (1, 0, 0)),
                constraints=CONSTRAINTS,
            )

    def test_invalid_sample_fails_closed(self) -> None:
        sample = make_locus_sample(icrs_ra_deg=float("nan"), icrs_dec_deg=float("nan"))
        result = visibility_sample(
            sample=sample,
            epoch=Epoch(epoch_id="e1", time=T0),
            observer=SITE,
            ephemeris=FakeEphemeris((0, 0, 0), (1, 0, 0)),
            constraints=CONSTRAINTS,
        )
        assert not result.constraints_passed
        assert result.failed_constraints == ("sample_invalid",)
        assert math.isnan(result.altitude_deg)

    def test_real_geometry_sanity(self) -> None:
        from sglseti.ephemeris import AstropyEphemeris

        result = visibility_sample(
            sample=make_locus_sample(),
            epoch=Epoch(epoch_id="e1", time=T0),
            observer=SITE,
            ephemeris=AstropyEphemeris(),
            constraints=CONSTRAINTS,
        )
        assert -90.0 <= result.altitude_deg <= 90.0
        assert 0.0 <= result.azimuth_deg < 360.0
        # 2021-11-06T03:00 UTC is 20:00 local at Kitt Peak: the Sun is down.
        assert result.sun_altitude_deg < -12.0
        assert 0.0 <= result.moon_separation_deg <= 180.0
        assert result.epoch_id == "e1"
