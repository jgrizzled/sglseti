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
        model_version="1.1.0",
        target_source_hash="sha256:test",
        ephemeris_id="fake_fixture_ephemeris",
        validity=Validity.VALID,
        uncertainty_method=UncertaintyMethod.NOT_PROPAGATED,
    )
    values.update(overrides)
    return LocusSample(**values)


def build_small_result(
    *,
    planned: bool = False,
    ephemeris: Any | None = None,
    target_distance_au: float = 200_000.0,
    **request_overrides: Any,
) -> Any:
    """A small, fully deterministic CalculationResult for export tests.

    Uses a synthetic target and the fixture FakeEphemeris; with
    ``planned=True`` a permissive-constraint commensal plan (visibility and
    pointings) is attached.
    """
    from astropy.time import Time

    from sglseti.generate import generate_loci
    from sglseti.models import (
        AstrometricState,
        CoordinateProduct,
        EndpointKind,
        Epoch,
        FieldOfView,
        GeometryRequest,
        ObservabilityConstraints,
        Observer,
        OutputFormat,
        RelayRange,
        Role,
        SamplingKind,
        SamplingSpec,
        Target,
        TimeList,
    )
    from sglseti.planning import plan_commensal
    from sglseti.targets import TargetRegistry

    target = Target(
        target_id="synth",
        display_name="Synthetic",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=100.0,
            pm_dec_mas_per_yr=-50.0,
            reference_epoch_jyear=2016.0,
            reference_epoch_scale="tdb",
            source="export test values",
            distance_pc=target_distance_au / AU_PER_PC,
            radial_velocity_km_s=0.0,
        ),
    )
    registry = TargetRegistry.from_targets((target,))
    values: dict[str, Any] = dict(
        target_ids=("synth",),
        roles=(Role.RX, Role.TX),
        time=TimeList(
            epochs=(
                Epoch(
                    epoch_id="e1",
                    time=Time("2021-11-06T00:00:00", scale="utc"),
                    metadata={"dataset_id": "D1"},
                ),
                Epoch(epoch_id="e2", time=Time("2022-03-01T12:00:00", scale="utc")),
            )
        ),
        observer=Observer.from_geodetic("test-site", -111.6003, 31.9583, 2096.0),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=3),
        model_id="tusay2022_eq5_7_v1",
        output_formats=(
            OutputFormat.ECSV,
            OutputFormat.JSON,
            OutputFormat.CSV,
            OutputFormat.DS9,
        ),
        assumed_half_width_arcsec=30.0,
    )
    if planned:
        values.update(
            include_rates=True,
            coordinate_products=(CoordinateProduct.ICRS,),
            observability=ObservabilityConstraints(
                min_target_altitude_deg=-90.0,
                max_sun_altitude_deg=90.0,
                min_moon_separation_deg=0.0,
            ),
            fov=FieldOfView(radius_arcsec=3600.0, exposure_s=300.0),
        )
    values.update(request_overrides)
    request = GeometryRequest(**values)
    if ephemeris is None:
        ephemeris = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
    result = generate_loci(request, registry, ephemeris=ephemeris)
    if planned:
        result = plan_commensal(result, registry, ephemeris=ephemeris)
    return result


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
