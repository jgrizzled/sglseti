"""Crossing results for time-dependent spacecraft observers (§3.3, item 11).

Uses the real Wolf 359 outbound-beam scenario (frozen in
``wolf359_crossing_reference.yaml``) on the pinned DE440s excerpt kernel,
with tabular spacecraft observers built as the kernel Earth plus a fixed
barycentric displacement. Two sharp physical predictions verify the
beam-axis geometry end-to-end through the provider layer:

1. A displacement ALONG the beam axis changes the observer's along-axis
   distance but not its perpendicular offset, so the crossing epoch and
   ``b_min`` must be essentially unchanged (residual: the axis direction's
   slow proper-motion drift across the displacement, sub-1e-6 AU).
2. A displacement ACROSS the axis shifts the crossing by exactly its
   magnitude, split between the impact parameter and the crossing time:
   ``sqrt((b_new - b_old)^2 + (v_perp * dt)^2) ~= |displacement|``
   (the perpendicular plane is two-dimensional; the displacement is chosen
   smaller than ``b_min`` so the crossing stays on one side of the axis).

The uncertainty-aware crossing products and the observation-interval
impact minimum are exercised with the spacecraft observer as well — the
§3.3 "results for time-dependent spacecraft observers" deliverable.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table
from astropy.time import Time, TimeDelta
from support import load_reference_fixture

from sglseti.crossings import find_crossings, minimize_impact_parameter
from sglseti.ephemeris import AstropyEphemeris
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.models import (
    AstrometricState,
    CrossingsRequest,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    LinkDirection,
    ObservationInterval,
    Observer,
    ParameterProvenance,
    Target,
    TimeInterval,
    Validity,
)
from sglseti.provenance import file_sha256
from sglseti.providers import clear_provider_cache
from sglseti.targets import TargetRegistry
from sglseti.uncertainty import crossing_uncertainty

pytest.importorskip("jplephem")

FIXTURE = load_reference_fixture("wolf359_crossing_reference.yaml")
KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / ("de440s_excerpt_2010-2035.bsp")


def wolf359_target(with_uncertainty: bool = False) -> Target:
    astrometry = FIXTURE["astrometry"]
    provenance = (
        (
            ParameterProvenance("ra_deg", "benchmark-scale demo", 200.0, "mas"),
            ParameterProvenance("dec_deg", "benchmark-scale demo", 200.0, "mas"),
        )
        if with_uncertainty
        else ()
    )
    return Target(
        target_id="wolf-359",
        display_name="Wolf 359",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=astrometry["ra_deg"],
            dec_deg=astrometry["dec_deg"],
            parallax_mas=astrometry["parallax_mas"],
            pm_ra_cosdec_mas_per_yr=astrometry["pm_ra_cosdec_mas_per_yr"],
            pm_dec_mas_per_yr=astrometry["pm_dec_mas_per_yr"],
            radial_velocity_km_s=astrometry["radial_velocity_km_s"],
            reference_epoch_jyear=astrometry["reference_epoch_jyear"],
            reference_epoch_scale=astrometry["reference_epoch_scale"],
            source="Gaia EDR3 via SIMBAD; see wolf359_crossing_reference.py",
        ),
        parameter_provenance=provenance,
    )


@pytest.fixture(scope="module")
def kernel_ephemeris() -> AstropyEphemeris:
    return AstropyEphemeris(EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL)))


def spacecraft_table(
    tmp_path: Path,
    name: str,
    ephemeris: AstropyEphemeris,
    displacement_au: np.ndarray,
) -> Observer:
    """Tabulate kernel-Earth + a fixed displacement, with Hermite velocities."""
    start = Time("2015-07-25T00:00:00", scale="utc").tdb
    epochs_jd, positions, velocities = [], [], []
    half_day = TimeDelta(0.5, format="jd", scale="tdb")
    for day in range(76):  # through 2015-10-08
        time = start + TimeDelta(float(day), format="jd", scale="tdb")
        earth = ephemeris.earth_barycentric_au(time)
        velocity = ephemeris.earth_barycentric_au(time + half_day) - ephemeris.earth_barycentric_au(
            time - half_day
        )  # AU/day, central difference
        epochs_jd.append(float(time.tdb.jd))
        positions.append(earth + displacement_au)
        velocities.append(velocity)
    path = tmp_path / f"{name}.ecsv"
    Table(
        {
            "epoch_tdb_jd": epochs_jd,
            "x_au": [p[0] for p in positions],
            "y_au": [p[1] for p in positions],
            "z_au": [p[2] for p in positions],
            "vx_au_per_day": [v[0] for v in velocities],
            "vy_au_per_day": [v[1] for v in velocities],
            "vz_au_per_day": [v[2] for v in velocities],
        }
    ).write(path, format="ascii.ecsv", overwrite=True)
    return Observer.spacecraft_table(name, str(path), checksum_sha256=file_sha256(path))


def crossing_request(observer: Observer) -> CrossingsRequest:
    return CrossingsRequest(
        target_ids=("wolf-359",),
        link_directions=(LinkDirection.OUTBOUND,),
        intervals=(
            TimeInterval(
                interval_id="conjunction-2015",
                start=Time("2015-08-01T00:00:00", scale="utc"),
                stop=Time("2015-10-01T00:00:00", scale="utc"),
            ),
        ),
        observer=observer,
        relay_distance_au=FIXTURE["relay_distance_au"],
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=5.0,
        refine_tolerance_s=10.0,
        ephemeris=EphemerisSpec(adapter=EphemerisAdapter.JPL_FILE, path=str(KERNEL)),
    )


def deepest_event(observer: Observer):
    registry = TargetRegistry.from_targets((wolf359_target(),))
    result = find_crossings(crossing_request(observer), registry, strict=True)
    events = [e for e in result.events if e.validity is not Validity.INVALID]
    assert events
    return min(events, key=lambda e: e.b_min_au)


@pytest.fixture(scope="module")
def earth_event():
    clear_provider_cache()
    return deepest_event(Observer.earth_center())


def _axis_unit(event) -> np.ndarray:
    ra = math.radians(event.axis_icrs_ra_deg)
    dec = math.radians(event.axis_icrs_dec_deg)
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def test_earth_baseline_matches_frozen_fixture(earth_event) -> None:
    frozen = FIXTURE["years"][2015]
    assert earth_event.b_min_solar_radii == pytest.approx(frozen["computed_b_min_rsun"], abs=5e-3)
    assert earth_event.observer_provider_id == "earth_center_v1"


def test_along_axis_displacement_leaves_the_crossing_unchanged(
    tmp_path: Path, earth_event, kernel_ephemeris
) -> None:
    displacement = 0.002 * _axis_unit(earth_event)
    observer = spacecraft_table(tmp_path, "along-axis", kernel_ephemeris, displacement)
    event = deepest_event(observer)
    assert event.observer_provider_id == "spacecraft_table_v1"
    assert abs(event.b_min_au - earth_event.b_min_au) < 2e-6
    dt_s = abs(event.t_ca_tdb_jd - earth_event.t_ca_tdb_jd) * 86_400.0
    assert dt_s < 600.0


def test_cross_axis_displacement_shifts_the_crossing_by_its_magnitude(
    tmp_path: Path, earth_event, kernel_ephemeris
) -> None:
    axis = _axis_unit(earth_event)
    perpendicular = np.cross(axis, [0.0, 0.0, 1.0])
    perpendicular /= np.linalg.norm(perpendicular)
    magnitude = 0.002  # AU, smaller than b_min (~0.0035 AU): no side flip
    observer = spacecraft_table(tmp_path, "cross-axis", kernel_ephemeris, magnitude * perpendicular)
    event = deepest_event(observer)
    delta_b = event.b_min_au - earth_event.b_min_au
    delta_t_days = event.t_ca_tdb_jd - earth_event.t_ca_tdb_jd
    v_perp_au_per_day = earth_event.v_perp_km_s * 86_400.0 / 149_597_870.700
    recovered = math.hypot(delta_b, v_perp_au_per_day * delta_t_days)
    # The 2D perpendicular plane splits the displacement between b and
    # v*t exactly (up to path curvature over the time shift).
    assert recovered == pytest.approx(magnitude, rel=0.10)
    assert abs(delta_b) > 1e-5 or abs(delta_t_days) * v_perp_au_per_day > 1e-5
    assert event.side == earth_event.side


def test_uncertainty_and_interval_products_compose_with_spacecraft(
    tmp_path: Path, earth_event, kernel_ephemeris
) -> None:
    axis = _axis_unit(earth_event)
    perpendicular = np.cross(axis, [0.0, 0.0, 1.0])
    perpendicular /= np.linalg.norm(perpendicular)
    observer = spacecraft_table(
        tmp_path, "uncertain-craft", kernel_ephemeris, 0.001 * perpendicular
    )
    target = wolf359_target(with_uncertainty=True)
    registry = TargetRegistry.from_targets((target,))
    result = find_crossings(crossing_request(observer), registry, strict=True)
    event = min(
        (e for e in result.events if e.validity is not Validity.INVALID),
        key=lambda e: e.b_min_au,
    )
    uncertainty = crossing_uncertainty(
        event=event,
        target=target,
        observer=observer,
        ephemeris=kernel_ephemeris,
        model=Tusay2022Eq57V1(),
        seed=3,
        count=12,
        window_days=6.0,
        refine_tolerance_s=600.0,
    )
    assert uncertainty.sample_count == 12
    assert uncertainty.b_min_sigma_au >= 0.0
    assert uncertainty.b_min_lower_au <= uncertainty.b_min_median_au <= uncertainty.b_min_upper_au
    assert uncertainty.side_consistency_fraction == 1.0

    exposure = ObservationInterval(
        interval_id="sc-exposure",
        start=Time(event.t_ca_tdb_jd - 0.5, format="jd", scale="tdb"),
        stop=Time(event.t_ca_tdb_jd + 0.5, format="jd", scale="tdb"),
    )
    sample = minimize_impact_parameter(
        target=target,
        interval=exposure,
        link_direction=LinkDirection.OUTBOUND,
        observer=observer,
        z_au=FIXTURE["relay_distance_au"],
        ephemeris=kernel_ephemeris,
    )
    assert sample.b_au == pytest.approx(event.b_min_au, rel=1e-3)
    assert sample.observer_id == "uncertain-craft"


def test_impact_parameter_point_query_consistency(
    tmp_path: Path, earth_event, kernel_ephemeris
) -> None:
    """The point API and the scan agree at the scan's closest approach."""
    from sglseti.crossings import impact_parameter

    axis = _axis_unit(earth_event)
    observer = spacecraft_table(tmp_path, "point-query", kernel_ephemeris, 0.002 * axis)
    event = deepest_event(observer)
    sample = impact_parameter(
        target=wolf359_target(),
        time=Time(event.t_ca_tdb_jd, format="jd", scale="tdb"),
        link_direction=LinkDirection.OUTBOUND,
        observer=observer,
        z_au=FIXTURE["relay_distance_au"],
        ephemeris=kernel_ephemeris,
    )
    assert sample.b_au == pytest.approx(event.b_min_au, rel=1e-9)
    assert sample.side == event.side
