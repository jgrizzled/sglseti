"""Shared test helpers: fixture loading and a deterministic fake ephemeris."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

REFERENCE_DIR = Path(__file__).resolve().parent / "data" / "reference"
EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"

AU_PER_PC = 648_000 / math.pi


def load_reference_fixture(name: str) -> dict[str, Any]:
    with (REFERENCE_DIR / name).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


class FakeEphemeris:
    """Fixed barycentric vectors, optionally with limited time coverage.

    Setting ``earth`` to a synthetic fixture's observer vector and using an
    Earth-center observer injects that exact observer position into the
    geometry engine.
    """

    def __init__(
        self,
        sun_au: tuple[float, float, float],
        earth_au: tuple[float, float, float],
        coverage_jd: tuple[float, float] | None = None,
        moon_au: tuple[float, float, float] | None = None,
    ) -> None:
        import numpy as np

        self._sun = np.asarray(sun_au, dtype=float)
        self._earth = np.asarray(earth_au, dtype=float)
        # Default Moon: ~1 lunar distance from the fake Earth along +x.
        self._moon = (
            np.asarray(moon_au, dtype=float)
            if moon_au is not None
            else self._earth + np.array([0.00257, 0.0, 0.0])
        )
        self._coverage = coverage_jd

    @property
    def ephemeris_id(self) -> str:
        return "fake_fixture_ephemeris"

    def _check(self, time: Any) -> None:
        if self._coverage is not None:
            from sglseti.errors import EphemerisCoverageError

            jd = float(time.tdb.jd)
            if not self._coverage[0] <= jd <= self._coverage[1]:
                raise EphemerisCoverageError(
                    f"epoch jd={jd} outside fake coverage {self._coverage}"
                )

    def sun_barycentric_au(self, time: Any) -> Any:
        self._check(time)
        return self._sun.copy()

    def earth_barycentric_au(self, time: Any) -> Any:
        self._check(time)
        return self._earth.copy()

    def moon_barycentric_au(self, time: Any) -> Any:
        self._check(time)
        return self._moon.copy()


def make_locus_sample(**overrides: Any) -> Any:
    """A valid LocusSample with plausible defaults, for pure-logic tests."""
    from sglseti.models import (
        LocusSample,
        Role,
        TargetEventKind,
        UncertaintyMethod,
        Validity,
    )

    values: dict[str, Any] = dict(
        calculation_id="calc-test",
        epoch_id="e1",
        target_id="synth",
        role=Role.RX,
        sample_id="smp-test",
        observation_time_utc="2021-11-06T00:00:00.000",
        observation_time_tdb_jd=2459524.5008,
        catalog_direction_epoch_tdb_jd=2459518.1478,
        relay_event_epoch_tdb_jd_approx=2459521.3243,
        solar_lens_epoch_tdb_jd_approx=2459518.1478,
        target_event_epoch_tdb_jd_approx=2458363.0441,
        target_event_kind=TargetEventKind.EMISSION,
        target_light_time_days=1155.1037,
        sun_relay_light_time_days=3.1765,
        observer_relay_light_time_days_approx=3.1765,
        z_au=550.0,
        q_per_au=1.0 / 550.0,
        icrs_ra_deg=39.85,
        icrs_dec_deg=60.90,
        observer_id="test-site",
        model_id="tusay2022_eq5_7_v1",
        model_version="1.0.0",
        target_source_hash="sha256:test",
        ephemeris_id="fake_fixture_ephemeris",
        validity=Validity.VALID,
        uncertainty_method=UncertaintyMethod.NOT_PROPAGATED,
    )
    values.update(overrides)
    return LocusSample(**values)


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation, pure math (no astropy)."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dra = math.radians(ra2 - ra1)
    # Vincenty formula for numerical stability at small separations.
    num = math.hypot(
        math.cos(p2) * math.sin(dra),
        math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dra),
    )
    den = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dra)
    return math.degrees(math.atan2(num, den)) * 3600.0
