"""Propagated uncertainty products (roadmap §2.3, §3.3).

Monte Carlo propagation of the target-state uncertainties declared in a
schema-v2 registry through the complete target-generation calculation:

- :func:`target_uncertainty` assembles the sampling covariance from
  per-value provenance uncertainties and an optional full
  covariance/correlation matrix;
- :func:`draw_target_samples` draws perturbed but fully validated targets
  (domain-violating draws are rejected and redrawn, which is also the
  explicit treatment of non-Gaussian orbital uncertainty: Gaussian element
  draws propagate through Kepler's equation into a non-Gaussian direction
  distribution, and all percentiles below are empirical);
- :func:`propagate_locus_uncertainty` produces the sky-plane uncertainty of
  one locus direction — nominal point, sample offsets suitable for
  constructing sky regions, a declared confidence level with its empirical
  confidence radius, sky covariance, and along/cross-track sigmas relative
  to the local corridor tangent (relay-distance sampling describes the
  locus ALONG the corridor; this is the cross-track knowledge it cannot
  provide);
- :func:`crossing_uncertainty` re-minimizes the beam-axis impact parameter
  near a nominal crossing event per sampled target, yielding distributions
  and bounds on ``b_min``, closest-approach time, and transverse speed,
  plus side-of-axis stability.

Every product records the sampling seed, sample count, and confidence
level, and labels the uncertainty contributions explicitly: only the
target state is propagated in v1.1 — observer state, ephemeris, and
geometry-model floors are declared ``not_propagated``, never silently
absorbed. A propagated confidence region is structurally distinct from an
assumed search pad (``assumed_half_width_arcsec`` products keep their
``assumed`` labeling; these records carry ``UncertaintyMethod.PROPAGATED``).
Invalid or degraded samples are counted and surfaced exactly as nominal
geometry failures are.

Sampling units convention (Gaia-style): position uncertainties are
tangent-plane offsets in mas (``ra_deg`` means ``d(ra)*cos(dec)``), proper
motions in mas/yr, parallax in mas, distance in pc, radial velocity in
km/s, accelerations in mas/yr2, and orbital elements in their storage
units (yr, arcsec, deg, dimensionless ``1``). Declared uncertainty units
must match exactly; a mismatch is an error, not a silent conversion.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from astropy.time import Time, TimeDelta

from .crossings import (
    KM_PER_AU,
    V_PERP_STEP_S,
    _axis_state,
    _golden_minimize,
)
from .ephemeris import Ephemeris
from .errors import GenerationError
from .geometry import GeometryModel
from .locus import evaluate_locus
from .models import (
    BeamSide,
    CovarianceKind,
    CrossingEvent,
    LinkDirection,
    LocusPoint,
    Observer,
    Role,
    Target,
    UncertaintyMethod,
    Validity,
)

__all__ = [
    "CONTRIBUTION_EPHEMERIS",
    "CONTRIBUTION_MODEL_FLOOR",
    "CONTRIBUTION_OBSERVER_STATE",
    "CONTRIBUTION_TARGET_STATE",
    "WARN_DEGRADED_SAMPLES",
    "WARN_INVALID_SAMPLES",
    "WARN_MINIMUM_AT_WINDOW_EDGE",
    "CrossingUncertainty",
    "LocusUncertainty",
    "TargetUncertainty",
    "crossing_uncertainty",
    "draw_target_samples",
    "propagate_locus_uncertainty",
    "target_uncertainty",
]

#: Uncertainty-contribution labels (§2.3): what is propagated and what is
#: explicitly not. v1.1 propagates the target state only.
CONTRIBUTION_TARGET_STATE = "target_state:propagated"
CONTRIBUTION_OBSERVER_STATE = "observer_state:not_propagated"
CONTRIBUTION_EPHEMERIS = "ephemeris:not_propagated"
CONTRIBUTION_MODEL_FLOOR = "geometry_model_floor:not_propagated"

_CONTRIBUTIONS = (
    CONTRIBUTION_TARGET_STATE,
    CONTRIBUTION_OBSERVER_STATE,
    CONTRIBUTION_EPHEMERIS,
    CONTRIBUTION_MODEL_FLOOR,
)

#: Warning codes attached to propagated products (counts appended).
WARN_DEGRADED_SAMPLES = "degraded_uncertainty_samples"
WARN_INVALID_SAMPLES = "invalid_uncertainty_samples"
WARN_MINIMUM_AT_WINDOW_EDGE = "minimum_at_window_edge"

#: Sampleable parameter -> required uncertainty unit. Parameter names are
#: the registry provenance field names; position units are tangent-plane
#: mas (``ra_deg`` uncertainty means ``d(ra)*cos(dec)``).
SAMPLEABLE_PARAMETER_UNITS = {
    "ra_deg": "mas",
    "dec_deg": "mas",
    "parallax_mas": "mas",
    "distance_pc": "pc",
    "pm_ra_cosdec_mas_per_yr": "mas/yr",
    "pm_dec_mas_per_yr": "mas/yr",
    "radial_velocity_km_s": "km/s",
    "accel_ra_cosdec_mas_per_yr2": "mas/yr2",
    "accel_dec_mas_per_yr2": "mas/yr2",
    "period_yr": "yr",
    "periastron_epoch_jyear": "yr",
    "eccentricity": "1",
    "semimajor_axis_arcsec": "arcsec",
    "inclination_deg": "deg",
    "ascending_node_deg": "deg",
    "arg_periastron_deg": "deg",
    "mass_fraction_secondary": "1",
}

_ASTROMETRY_FIELDS = frozenset(
    {
        "ra_deg",
        "dec_deg",
        "parallax_mas",
        "distance_pc",
        "pm_ra_cosdec_mas_per_yr",
        "pm_dec_mas_per_yr",
        "radial_velocity_km_s",
    }
)
_ACCELERATION_FIELDS = frozenset(
    {"accel_ra_cosdec_mas_per_yr2", "accel_dec_mas_per_yr2"}
)
_CIRCULAR_ORBIT_ANGLES = frozenset({"ascending_node_deg", "arg_periastron_deg"})

_MAS_PER_DEG = 3.6e6
_REJECTION_FACTOR = 50


# ---------------------------------------------------------------------------
# Target sampling model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetUncertainty:
    """The assembled Gaussian sampling model of one target's parameters.

    ``parameters`` fixes the ordering of ``covariance`` (canonical units of
    :data:`SAMPLEABLE_PARAMETER_UNITS`); ``sigmas`` is its diagonal square
    root. The propagated DIRECTION distribution is generally non-Gaussian
    (orbital elements pass through Kepler's equation); this record only
    describes the input-parameter draw.
    """

    target_id: str
    parameters: tuple[str, ...]
    units: tuple[str, ...]
    sigmas: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]


def target_uncertainty(target: Target) -> TargetUncertainty:
    """Assemble the sampling covariance a target's registry entry declares.

    Sources, combined strictly: per-value provenance uncertainties give
    independent diagonal terms; a covariance matrix (parameters named by
    the registry field names above) is used directly; a correlation matrix
    requires a provenance sigma for each of its parameters. A parameter
    present in both a covariance matrix and provenance must agree, and
    every declared unit must match the canonical sampling unit exactly.
    Raises :class:`~sglseti.errors.GenerationError` when nothing usable is
    declared or the declaration is ambiguous.
    """
    if target.provider_id == "sampled_state_v1":
        raise GenerationError(
            f"target {target.target_id!r} uses sampled_state_v1: its states "
            "come from an external ephemeris, so parameter sampling does not "
            "apply — express uncertainty in the sampled ephemeris itself "
            "(improvements §2.3 non-Gaussian treatment)"
        )
    provenance = {entry.parameter: entry for entry in target.parameter_provenance}
    sigmas: dict[str, float] = {}
    for name, entry in provenance.items():
        if entry.uncertainty is None:
            continue
        if name not in SAMPLEABLE_PARAMETER_UNITS:
            raise GenerationError(
                f"target {target.target_id!r}: provenance uncertainty for "
                f"{name!r} is not a sampleable parameter; supported: "
                f"{sorted(SAMPLEABLE_PARAMETER_UNITS)}"
            )
        expected = SAMPLEABLE_PARAMETER_UNITS[name]
        if entry.unit != expected:
            raise GenerationError(
                f"target {target.target_id!r}: uncertainty for {name!r} has "
                f"unit {entry.unit!r}; sampling requires {expected!r} "
                "(no silent conversion)"
            )
        sigmas[name] = float(entry.uncertainty)

    ordered: list[str] = []
    spec = target.covariance
    if spec is not None:
        for index, name in enumerate(spec.parameters):
            if name not in SAMPLEABLE_PARAMETER_UNITS:
                raise GenerationError(
                    f"target {target.target_id!r}: covariance parameter "
                    f"{name!r} is not a sampleable parameter; name it one of "
                    f"{sorted(SAMPLEABLE_PARAMETER_UNITS)}"
                )
            expected = SAMPLEABLE_PARAMETER_UNITS[name]
            if spec.units[index] != expected:
                raise GenerationError(
                    f"target {target.target_id!r}: covariance unit for "
                    f"{name!r} is {spec.units[index]!r}; sampling requires "
                    f"{expected!r}"
                )
        ordered.extend(spec.parameters)
    ordered.extend(sorted(name for name in sigmas if name not in ordered))
    if not ordered:
        raise GenerationError(
            f"target {target.target_id!r} declares no usable uncertainties; "
            "propagation requires per-value uncertainties or a covariance "
            "matrix (registry schema v2)"
        )

    size = len(ordered)
    matrix = np.zeros((size, size))
    if spec is not None:
        block = len(spec.parameters)
        if spec.kind is CovarianceKind.COVARIANCE:
            for i in range(block):
                for j in range(block):
                    matrix[i, j] = spec.matrix[i][j]
            for index, name in enumerate(spec.parameters):
                if name in sigmas:
                    diagonal_sigma = math.sqrt(spec.matrix[index][index])
                    if not math.isclose(
                        diagonal_sigma, sigmas[name], rel_tol=1e-6, abs_tol=0.0
                    ):
                        raise GenerationError(
                            f"target {target.target_id!r}: {name!r} declares "
                            f"sigma {sigmas[name]} in provenance but "
                            f"{diagonal_sigma} on the covariance diagonal; "
                            "resolve the ambiguity"
                        )
        else:  # correlation: needs provenance sigmas for scale
            missing = [name for name in spec.parameters if name not in sigmas]
            if missing:
                raise GenerationError(
                    f"target {target.target_id!r}: correlation matrix needs "
                    f"provenance uncertainties for {missing}"
                )
            for i, name_i in enumerate(spec.parameters):
                for j, name_j in enumerate(spec.parameters):
                    matrix[i, j] = (
                        spec.matrix[i][j] * sigmas[name_i] * sigmas[name_j]
                    )
    for index, name in enumerate(ordered):
        if matrix[index, index] == 0.0:
            matrix[index, index] = sigmas[name] ** 2

    eigenvalues = np.linalg.eigvalsh(matrix)
    if float(eigenvalues.min()) < -1e-12 * max(1.0, float(eigenvalues.max())):
        raise GenerationError(
            f"target {target.target_id!r}: assembled covariance is not "
            "positive semi-definite; check the declared matrix"
        )
    return TargetUncertainty(
        target_id=target.target_id,
        parameters=tuple(ordered),
        units=tuple(SAMPLEABLE_PARAMETER_UNITS[name] for name in ordered),
        sigmas=tuple(math.sqrt(max(0.0, float(matrix[i, i]))) for i in range(size)),
        covariance=tuple(tuple(float(v) for v in row) for row in matrix),
    )


def _apply_offsets(
    target: Target, parameters: tuple[str, ...], deltas: np.ndarray
) -> Target:
    """One perturbed target; raises ValueError when a draw leaves a domain."""
    astrometry_updates: dict[str, Any] = {}
    orbit_updates: dict[str, Any] = {}
    acceleration_updates: dict[str, Any] = {}
    state = target.astrometry
    for name, delta_raw in zip(parameters, deltas, strict=True):
        delta = float(delta_raw)
        if name == "ra_deg":
            cos_dec = math.cos(math.radians(state.dec_deg))
            astrometry_updates["ra_deg"] = (
                state.ra_deg + delta / (_MAS_PER_DEG * cos_dec)
            ) % 360.0
        elif name == "dec_deg":
            astrometry_updates["dec_deg"] = state.dec_deg + delta / _MAS_PER_DEG
        elif name in _ASTROMETRY_FIELDS:
            current = getattr(state, name)
            if current is None:
                raise GenerationError(
                    f"target {target.target_id!r}: uncertainty declared for "
                    f"{name!r} but the target does not carry that value"
                )
            astrometry_updates[name] = float(current) + delta
        elif name in _ACCELERATION_FIELDS:
            if target.acceleration is None:
                raise GenerationError(
                    f"target {target.target_id!r}: uncertainty declared for "
                    f"{name!r} but the target has no acceleration terms"
                )
            acceleration_updates[name] = getattr(target.acceleration, name) + delta
        else:  # orbital element
            if target.orbit is None:
                raise GenerationError(
                    f"target {target.target_id!r}: uncertainty declared for "
                    f"{name!r} but the target has no orbit solution"
                )
            value = getattr(target.orbit, name) + delta
            if name in _CIRCULAR_ORBIT_ANGLES:
                value %= 360.0
            orbit_updates[name] = value

    updates: dict[str, Any] = {}
    if astrometry_updates:
        updates["astrometry"] = dataclasses.replace(state, **astrometry_updates)
    if orbit_updates:
        assert target.orbit is not None
        updates["orbit"] = dataclasses.replace(target.orbit, **orbit_updates)
    if acceleration_updates:
        assert target.acceleration is not None
        updates["acceleration"] = dataclasses.replace(
            target.acceleration, **acceleration_updates
        )
    return dataclasses.replace(target, **updates)


def draw_target_samples(
    target: Target, *, count: int, seed: int
) -> tuple[Target, ...]:
    """Draw ``count`` perturbed, fully validated targets.

    Deterministic for a given ``seed`` (recorded on every propagated
    product). Draws that violate a parameter domain (eccentricity, mass
    fraction, declination, ...) are rejected and redrawn — the explicit
    non-Gaussian treatment near domain boundaries — with a hard failure if
    rejection dominates, rather than a silently clipped (biased)
    distribution.
    """
    if count < 2:
        raise GenerationError(f"sample count must be at least 2, got {count}")
    model = target_uncertainty(target)
    rng = np.random.default_rng(seed)
    mean = np.zeros(len(model.parameters))
    covariance = np.asarray(model.covariance)
    samples: list[Target] = []
    attempts = 0
    while len(samples) < count:
        attempts += 1
        if attempts > _REJECTION_FACTOR * count:
            raise GenerationError(
                f"target {target.target_id!r}: rejection sampling failed "
                f"({attempts} draws for {count} samples); the declared "
                "uncertainties are inconsistent with the parameter domains"
            )
        deltas = rng.multivariate_normal(mean, covariance, method="svd")
        try:
            samples.append(_apply_offsets(target, model.parameters, deltas))
        except ValueError:
            continue
    return tuple(samples)


# ---------------------------------------------------------------------------
# Propagated locus uncertainty (§2.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocusUncertainty:
    """Propagated sky-plane uncertainty of one locus direction.

    ``offsets_arcsec`` are per-sample tangent-plane offsets
    ``(d_ra_cosdec, d_dec)`` from the nominal direction — samples suitable
    for constructing sky regions. ``confidence_radius_arcsec`` is the
    EMPIRICAL radial quantile at ``confidence_level`` (no Gaussian
    assumption); ``covariance_arcsec2`` and the along/cross-track sigmas
    (relative to the local corridor tangent) are moments, meaningful where
    the distribution is locally compact. A propagated product is
    structurally distinct from an assumed search pad.
    """

    target_id: str
    role: Role
    observation_time: Time
    observer_id: str
    z_au: float
    method: UncertaintyMethod
    sample_count: int
    seed: int
    confidence_level: float
    nominal: LocusPoint
    offsets_arcsec: tuple[tuple[float, float], ...]
    confidence_radius_arcsec: float
    covariance_arcsec2: tuple[tuple[float, float], tuple[float, float]]
    along_track_sigma_arcsec: float
    cross_track_sigma_arcsec: float
    contributions: tuple[str, ...]
    distribution: str
    model_id: str
    model_version: str
    ephemeris_id: str
    validity: Validity
    degraded_sample_count: int = 0
    invalid_sample_count: int = 0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError(
                f"confidence_level must be within (0, 1), got {self.confidence_level}"
            )
        if len(self.offsets_arcsec) != self.sample_count:
            raise ValueError("offsets_arcsec must carry one entry per sample")


def _east_north_basis(vec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
    ra = math.atan2(y, x)
    east = np.array([-math.sin(ra), math.cos(ra), 0.0])
    horizontal = math.hypot(x, y)
    north = np.array(
        [-z * math.cos(ra), -z * math.sin(ra), horizontal]
    )
    north /= np.linalg.norm(north)
    return east, north


def _unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    vector: np.ndarray = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    return vector


def _tangent_offset_arcsec(
    sample_vec: np.ndarray,
    nominal_vec: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
) -> tuple[float, float]:
    radial = float(np.dot(sample_vec, nominal_vec))
    d_east = math.atan2(float(np.dot(sample_vec, east)), radial)
    d_north = math.atan2(float(np.dot(sample_vec, north)), radial)
    return math.degrees(d_east) * 3600.0, math.degrees(d_north) * 3600.0


def propagate_locus_uncertainty(
    *,
    target: Target,
    role: Role,
    observation_time: Time,
    observer: Observer,
    z_au: float,
    ephemeris: Ephemeris,
    model: GeometryModel,
    seed: int,
    count: int = 256,
    confidence_level: float = 0.95,
) -> LocusUncertainty:
    """Monte Carlo sky-plane uncertainty of one locus direction (§2.3)."""

    def point_at(sampled: Target) -> LocusPoint:
        return evaluate_locus(
            target=sampled,
            role=role,
            observation_time=observation_time,
            observer=observer,
            z_au=z_au,
            ephemeris=ephemeris,
            model=model,
        )

    nominal = point_at(target)
    nominal_vec = _unit(nominal.icrs_ra_deg, nominal.icrs_dec_deg)
    east, north = _east_north_basis(nominal_vec)

    offsets: list[tuple[float, float]] = []
    degraded = 0
    invalid = 0
    for sampled in draw_target_samples(target, count=count, seed=seed):
        point = point_at(sampled)
        if point.validity is Validity.INVALID or not math.isfinite(point.icrs_ra_deg):
            invalid += 1
            offsets.append((float("nan"), float("nan")))
            continue
        if point.validity is Validity.DEGRADED:
            degraded += 1
        offsets.append(
            _tangent_offset_arcsec(
                _unit(point.icrs_ra_deg, point.icrs_dec_deg),
                nominal_vec,
                east,
                north,
            )
        )

    finite = np.array([o for o in offsets if math.isfinite(o[0])])
    if len(finite) < 2:
        raise GenerationError(
            f"target {target.target_id!r}: fewer than two finite uncertainty "
            "samples; the propagation cannot be summarized"
        )
    radii = np.hypot(finite[:, 0], finite[:, 1])
    covariance = np.cov(finite.T, ddof=1)

    # Local corridor tangent: the direction of increasing z, from a small
    # reciprocal-distance step around the nominal point.
    q = 1.0 / z_au
    step_points = [
        evaluate_locus(
            target=target,
            role=role,
            observation_time=observation_time,
            observer=observer,
            z_au=1.0 / (q * factor),
            ephemeris=ephemeris,
            model=model,
        )
        for factor in (1.01, 0.99)
    ]
    tangent_pair = [
        _tangent_offset_arcsec(
            _unit(p.icrs_ra_deg, p.icrs_dec_deg), nominal_vec, east, north
        )
        for p in step_points
    ]
    tangent = np.array(tangent_pair[1]) - np.array(tangent_pair[0])
    norm = float(np.linalg.norm(tangent))
    if norm > 0.0:
        tangent /= norm
    else:  # degenerate tangent: fall back to an arbitrary fixed axis
        tangent = np.array([1.0, 0.0])
    normal = np.array([-tangent[1], tangent[0]])
    along_sigma = float(np.std(finite @ tangent, ddof=1))
    cross_sigma = float(np.std(finite @ normal, ddof=1))

    warnings: list[str] = list(nominal.warnings)
    validity = nominal.validity
    if degraded:
        warnings.append(f"{WARN_DEGRADED_SAMPLES}:{degraded}")
    if invalid:
        warnings.append(f"{WARN_INVALID_SAMPLES}:{invalid}")
        if validity is Validity.VALID:
            validity = Validity.DEGRADED

    return LocusUncertainty(
        target_id=target.target_id,
        role=role,
        observation_time=observation_time,
        observer_id=observer.observer_id,
        z_au=float(z_au),
        method=UncertaintyMethod.PROPAGATED,
        sample_count=count,
        seed=seed,
        confidence_level=confidence_level,
        nominal=nominal,
        offsets_arcsec=tuple((float(a), float(b)) for a, b in offsets),
        confidence_radius_arcsec=float(np.quantile(radii, confidence_level)),
        covariance_arcsec2=(
            (float(covariance[0, 0]), float(covariance[0, 1])),
            (float(covariance[1, 0]), float(covariance[1, 1])),
        ),
        along_track_sigma_arcsec=along_sigma,
        cross_track_sigma_arcsec=cross_sigma,
        contributions=_CONTRIBUTIONS,
        distribution="monte_carlo",
        model_id=model.model_id,
        model_version=model.model_version,
        ephemeris_id=ephemeris.ephemeris_id,
        validity=validity,
        degraded_sample_count=degraded,
        invalid_sample_count=invalid,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Uncertainty-aware crossings (§3.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossingUncertainty:
    """Distributions and bounds on one crossing's closest approach.

    The primary product remains the impact parameter: ``b_min`` bounds are
    the empirical ``(1-c)/2``, median, and ``(1+c)/2`` quantiles at the
    declared confidence level ``c``, with the full sample list retained.
    ``side_consistency_fraction`` is the fraction of samples whose
    side-of-axis matches the nominal event — side stability under the
    uncertainty model.
    """

    event_id: str
    target_id: str
    link_direction: LinkDirection
    observer_id: str
    z_au: float
    method: UncertaintyMethod
    sample_count: int
    seed: int
    confidence_level: float
    b_min_nominal_au: float
    b_min_lower_au: float
    b_min_median_au: float
    b_min_upper_au: float
    b_min_sigma_au: float
    b_min_samples_au: tuple[float, ...]
    t_ca_nominal_tdb_jd: float
    t_ca_lower_tdb_jd: float
    t_ca_median_tdb_jd: float
    t_ca_upper_tdb_jd: float
    t_ca_sigma_days: float
    v_perp_sigma_km_s: float
    side_nominal: BeamSide | None
    side_consistency_fraction: float
    window_days: float
    refine_tolerance_s: float
    axis_model_id: str
    axis_model_version: str
    model_id: str
    model_version: str
    ephemeris_id: str
    validity: Validity
    contributions: tuple[str, ...] = _CONTRIBUTIONS
    distribution: str = "monte_carlo"
    window_edge_count: int = 0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError(
                f"confidence_level must be within (0, 1), got {self.confidence_level}"
            )
        if len(self.b_min_samples_au) != self.sample_count:
            raise ValueError("b_min_samples_au must carry one entry per sample")


def crossing_uncertainty(
    *,
    event: CrossingEvent,
    target: Target,
    observer: Observer,
    ephemeris: Ephemeris,
    model: GeometryModel,
    seed: int,
    count: int = 128,
    confidence_level: float = 0.95,
    window_days: float = 90.0,
    refine_tolerance_s: float = 60.0,
) -> CrossingUncertainty:
    """Monte Carlo closest-approach distribution for one nominal event.

    Each sampled target's impact parameter is re-minimized inside a
    ``window_days`` span centered on the nominal closest approach — a local
    refinement, never a new multi-year scan. A sample whose minimum lands
    at the window edge is counted (:data:`WARN_MINIMUM_AT_WINDOW_EDGE`) and
    degrades the product: its true closest approach lies outside the
    window, so widen it.
    """
    if event.target_id != target.target_id:
        raise GenerationError(
            f"event {event.event_id} belongs to target {event.target_id!r}, "
            f"not {target.target_id!r}"
        )
    if not math.isfinite(event.t_ca_tdb_jd):
        raise GenerationError(
            f"event {event.event_id} is an invalid status row; there is no "
            "nominal closest approach to propagate around"
        )
    if window_days <= 0.0 or not math.isfinite(window_days):
        raise GenerationError(f"window_days must be positive, got {window_days}")

    start = Time(event.t_ca_tdb_jd, format="jd", scale="tdb") - TimeDelta(
        window_days / 2.0, format="jd", scale="tdb"
    )
    tolerance_days = refine_tolerance_s / 86_400.0
    half_step_days = V_PERP_STEP_S / 86_400.0 / 2.0

    def minimize(sampled: Target) -> tuple[float, float, float, BeamSide]:
        def b_at(offset_days: float) -> float:
            return _axis_state(
                target=sampled,
                time=start + TimeDelta(offset_days, format="jd", scale="tdb"),
                z_au=event.z_au,
                link_direction=event.link_direction,
                observer=observer,
                ephemeris=ephemeris,
                model=model,
            ).b_au

        offset = _golden_minimize(b_at, 0.0, window_days, tolerance_days)
        state = _axis_state(
            target=sampled,
            time=start + TimeDelta(offset, format="jd", scale="tdb"),
            z_au=event.z_au,
            link_direction=event.link_direction,
            observer=observer,
            ephemeris=ephemeris,
            model=model,
        )
        lo = max(0.0, offset - half_step_days)
        hi = min(window_days, offset + half_step_days)
        perp_rate = (
            _axis_state(
                target=sampled,
                time=start + TimeDelta(hi, format="jd", scale="tdb"),
                z_au=event.z_au,
                link_direction=event.link_direction,
                observer=observer,
                ephemeris=ephemeris,
                model=model,
            ).perp_au
            - _axis_state(
                target=sampled,
                time=start + TimeDelta(lo, format="jd", scale="tdb"),
                z_au=event.z_au,
                link_direction=event.link_direction,
                observer=observer,
                ephemeris=ephemeris,
                model=model,
            ).perp_au
        )
        v_perp = float(np.linalg.norm(perp_rate)) / (hi - lo) * KM_PER_AU / 86_400.0
        side = BeamSide.TARGET if state.s_au >= 0.0 else BeamSide.ANTI_TARGET
        return state.b_au, offset, v_perp, side

    b_values: list[float] = []
    t_offsets: list[float] = []
    v_values: list[float] = []
    sides: list[BeamSide] = []
    edge_count = 0
    for sampled in draw_target_samples(target, count=count, seed=seed):
        b_au, offset, v_perp, side = minimize(sampled)
        if offset <= 2.0 * tolerance_days or offset >= window_days - 2.0 * tolerance_days:
            edge_count += 1
        b_values.append(b_au)
        t_offsets.append(offset)
        v_values.append(v_perp)
        sides.append(side)

    b_array = np.asarray(b_values)
    t_array = np.asarray(t_offsets) + float(start.jd)
    lower_q = (1.0 - confidence_level) / 2.0
    upper_q = 1.0 - lower_q
    side_fraction = (
        float(np.mean([side is event.side for side in sides]))
        if event.side is not None
        else 0.0
    )

    warnings: list[str] = []
    validity = Validity.VALID
    if edge_count:
        warnings.append(f"{WARN_MINIMUM_AT_WINDOW_EDGE}:{edge_count}")
        validity = Validity.DEGRADED

    return CrossingUncertainty(
        event_id=event.event_id,
        target_id=target.target_id,
        link_direction=event.link_direction,
        observer_id=observer.observer_id,
        z_au=event.z_au,
        method=UncertaintyMethod.PROPAGATED,
        sample_count=count,
        seed=seed,
        confidence_level=confidence_level,
        b_min_nominal_au=event.b_min_au,
        b_min_lower_au=float(np.quantile(b_array, lower_q)),
        b_min_median_au=float(np.quantile(b_array, 0.5)),
        b_min_upper_au=float(np.quantile(b_array, upper_q)),
        b_min_sigma_au=float(np.std(b_array, ddof=1)),
        b_min_samples_au=tuple(float(b) for b in b_values),
        t_ca_nominal_tdb_jd=event.t_ca_tdb_jd,
        t_ca_lower_tdb_jd=float(np.quantile(t_array, lower_q)),
        t_ca_median_tdb_jd=float(np.quantile(t_array, 0.5)),
        t_ca_upper_tdb_jd=float(np.quantile(t_array, upper_q)),
        t_ca_sigma_days=float(np.std(np.asarray(t_offsets), ddof=1)),
        v_perp_sigma_km_s=float(np.std(np.asarray(v_values), ddof=1)),
        side_nominal=event.side,
        side_consistency_fraction=side_fraction,
        window_days=window_days,
        refine_tolerance_s=refine_tolerance_s,
        axis_model_id=event.axis_model_id,
        axis_model_version=event.axis_model_version,
        model_id=model.model_id,
        model_version=model.model_version,
        ephemeris_id=ephemeris.ephemeris_id,
        validity=validity,
        window_edge_count=edge_count,
        warnings=tuple(warnings),
    )
