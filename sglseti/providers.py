"""Target-state and observer-state provider protocols and baselines.

Roadmap item 6.1 (notes/improvements.md §2.1, §2.4): versioned provider
interfaces behind which richer endpoint and observer models can be added
without touching the geometry core. This module defines the protocols and
the two baseline families that preserve v1 behavior exactly:

- ``linear_astrometry_v1`` — the existing one-linear-six-dimensional
  catalog propagation (astropy ``apply_space_motion``), moved here verbatim
  from the geometry core;
- ``earth_center_v1`` / ``terrestrial_site_v1`` — the existing Earth-center
  and fixed-site barycentric observer construction (ephemeris Earth
  barycenter, plus the site's GCRS position vector treated as an ICRS-axis
  offset for sites).

Registry schema v2 (roadmap item 6.2) selects richer target-state families
implemented here on top of the linear baseline:

- ``acceleration_astrometry_v1`` — linear astrometry plus catalog quadratic
  (acceleration) proper-motion terms about the same reference epoch;
- ``two_body_orbit_v1`` — resolved components and system barycenters: a
  linearly propagating barycenter plus a published Campbell (visual-binary)
  orbital solution, with declared approximations;
- ``sampled_state_v1`` (roadmap item 6.9) — an externally generated,
  CHECKSUMMED cartesian ephemeris of the endpoint itself, with declared
  epoch semantics and interpolation; the only family that models
  ``planet`` endpoints.

Observer-state families beyond the baselines (roadmap item 6.8, §2.4),
selected by the :class:`~sglseti.models.Observer` spec's kind:

- ``solar_system_body_v1`` — a body served by the calculation's pinned
  planetary ephemeris;
- ``spacecraft_table_v1`` — a checksummed tabular ECSV ephemeris with
  declared interpolation (cubic Hermite with velocities, else linear);
- ``spacecraft_spice_v1`` — a SPICE SPK kernel (optional ``spiceypy``);
- ``programmatic_observer_v1`` — a runtime-registered state function for
  testing and specialized integrations.

Every provider declares its scientific metadata explicitly — epoch
semantics, frame, origin, validity/coverage, uncertainty or interpolation
policy, and a path-independent content identity — so a calculation can
record *which* adopted solution produced a state, not merely that one
did. v1 registries always resolve to the baselines.

Execution (roadmap §3.4): :func:`resolve_target_state_provider` memoizes
providers in a bounded LRU keyed by the target's stable content hash —
never object identity or location — and each provider memoizes its
propagated states per TDB epoch, so repeated target/role/epoch evaluations
(corridors over many relay distances, crossing scans, Monte Carlo loops)
reuse identical results instead of recomputing them. Memoization is pure:
providers are deterministic functions of immutable inputs, so cached and
uncached runs are bit-identical (:func:`clear_provider_cache` exists for
isolation in tests and benchmarks; the package is single-threaded by
design). Providers also expose vectorized evaluation — ``states_at`` for
target states and ``positions_au`` for observer positions — computing many
epochs in one astropy call for archive-scale consumers.

Like the geometry core, this is a heavy-import module (astropy at module
level); validation-only workflows never import it.
"""

from __future__ import annotations

import dataclasses
import math
import warnings as _warnings
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from astropy import units as u
from astropy.coordinates import Distance, EarthLocation, SkyCoord
from astropy.time import Time

from .ephemeris import Ephemeris, offline_resources
from .errors import EphemerisCoverageError, EphemerisError, GenerationError
from .models import Observer, ObserverKind, OrbitComponent, OrbitSolution, Target
from .provenance import file_sha256, stable_hash

__all__ = [
    "EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL",
    "LINEAR_PROPAGATION_SPAN_YEARS",
    "WARN_MISSING_RV",
    "AccelerationAstrometryV1",
    "EarthCenterObserverV1",
    "LinearAstrometryV1",
    "ObserverState",
    "ObserverStateProvider",
    "ProgrammaticObserverV1",
    "SampledStateV1",
    "SolarSystemBodyObserverV1",
    "SpiceSpacecraftObserverV1",
    "TabularSpacecraftObserverV1",
    "TargetState",
    "TargetStateProvider",
    "TerrestrialSiteObserverV1",
    "TwoBodyOrbitV1",
    "clear_provider_cache",
    "provider_cache_stats",
    "register_programmatic_observer",
    "resolve_observer_state_provider",
    "resolve_target_state_provider",
    "unregister_programmatic_observer",
]

#: Bounded LRU sizes for the identity-keyed memoization (§3.4). Both are
#: correctness-neutral: eviction only recomputes.
PROVIDER_CACHE_MAX = 64
STATE_CACHE_MAX = 4096

_PROVIDER_CACHE: OrderedDict[str, TargetStateProvider] = OrderedDict()
_PROVIDER_CACHE_STATS = {"hits": 0, "misses": 0}


def clear_provider_cache() -> None:
    """Drop all memoized providers (and their per-epoch state memos)."""
    _PROVIDER_CACHE.clear()
    _OBSERVER_CACHE.clear()
    _PROVIDER_CACHE_STATS["hits"] = 0
    _PROVIDER_CACHE_STATS["misses"] = 0


def provider_cache_stats() -> dict[str, int]:
    """Current provider-memo occupancy and hit/miss counters."""
    return {
        "providers": len(_PROVIDER_CACHE),
        "hits": _PROVIDER_CACHE_STATS["hits"],
        "misses": _PROVIDER_CACHE_STATS["misses"],
    }

#: Epoch semantics of the v1 catalog-propagation contract (ADR-0001): the
#: epoch handed to ``state_at`` is an SSB light-arrival epoch in the
#: Gaia/ERFA convention, never a physical target-event epoch.
EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL = "ssb_light_arrival_time"

#: Declared validity half-span of the linear family, in Julian years from
#: the catalog reference epoch (geometry_models.md §5). The geometry model
#: degrades — never rejects — states requested beyond it.
LINEAR_PROPAGATION_SPAN_YEARS = 75.0

#: Warning code attached when a flagged missing radial velocity propagates
#: as zero (explicitly, never silently).
WARN_MISSING_RV = "missing_radial_velocity"


# ---------------------------------------------------------------------------
# State records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetState:
    """One propagated target state at a provider-evaluated epoch.

    Direction and coordinate distance in the provider's declared frame and
    origin (baseline: barycentric ICRS). ``warnings`` carries evaluation
    diagnostics captured for this state (e.g. astropy propagation warnings).
    """

    epoch: Time
    ra_deg: float
    dec_deg: float
    distance_au: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObserverState:
    """One barycentric observer state at a provider-evaluated epoch.

    ``velocity_au_per_day`` is reserved for provider families that supply
    it (spacecraft ephemerides); the v1.1 baseline providers leave it
    ``None`` — consumers needing rates difference positions, as before.
    """

    epoch: Time
    position_au: tuple[float, float, float]
    velocity_au_per_day: tuple[float, float, float] | None = None


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class TargetStateProvider(Protocol):
    """A versioned source of propagated target states for one endpoint.

    Implementations declare their scientific contract as data: how the
    requested epoch is interpreted (``epoch_semantics``), the frame and
    origin of returned directions, the declared validity interval, the
    uncertainty model, and a path-independent content identity over the
    full adopted solution. ``warnings`` are solution-level conditions
    (e.g. a flagged missing radial velocity) that apply to every state the
    provider returns, as opposed to the per-evaluation warnings on each
    :class:`TargetState`.
    """

    provider_id: str
    provider_version: str
    epoch_semantics: str
    frame: str
    origin: str
    uncertainty_model: str

    @property
    def warnings(self) -> tuple[str, ...]:
        """Solution-level warning codes applying to every returned state."""
        ...

    @property
    def content_hash(self) -> str:
        """Stable identity of the adopted solution (never a file path)."""
        ...

    @property
    def validity_interval_jyear(self) -> tuple[float, float] | None:
        """Declared (start, stop) TDB Julian-year validity, or ``None``."""
        ...

    def state_at(self, epoch: Time) -> TargetState:
        """Propagated state at ``epoch`` (interpreted per epoch semantics)."""
        ...

    def states_at(self, epochs: Time) -> tuple[TargetState, ...]:
        """Vectorized propagation over a vector ``Time`` (§3.4).

        One astropy call for many epochs. Call-level astropy warnings are
        attached to every returned state (the vector path cannot attribute
        them per epoch), which is conservative relative to ``state_at``.
        """
        ...

    def propagation_span_years(self, epoch: Time) -> float | None:
        """Julian years between ``epoch`` and the best-constrained epoch.

        ``None`` when the provider has no single reference epoch. Geometry
        models compare this against their span-validity bounds.
        """
        ...


@runtime_checkable
class ObserverStateProvider(Protocol):
    """A versioned source of barycentric observer states at arbitrary epochs.

    Implementations declare frame, origin, evaluation time scale, coverage,
    interpolation policy, and content identity. ``coverage`` is a
    human-readable declaration; requesting a state outside the actual
    coverage raises :class:`~sglseti.errors.EphemerisCoverageError` rather
    than returning an apparently valid state.
    """

    provider_id: str
    provider_version: str
    frame: str
    origin: str
    time_scale: str
    interpolation: str

    @property
    def coverage(self) -> str | None:
        """Declared epoch coverage; ``None`` = bounded only by the ephemeris."""
        ...

    @property
    def content_hash(self) -> str:
        """Stable identity of the provider's inputs (never a file path)."""
        ...

    def state_at(self, epoch: Time) -> ObserverState:
        """Barycentric observer state at ``epoch``."""
        ...

    def positions_au(self, epochs: Time) -> np.ndarray:
        """Vectorized barycentric positions, shape ``(len(epochs), 3)`` AU."""
        ...


# ---------------------------------------------------------------------------
# Baseline target-state family
# ---------------------------------------------------------------------------


class LinearAstrometryV1:
    """The v1 linear-motion baseline: one 6-D catalog state, rigid propagation.

    Exactly the catalog construction and ``apply_space_motion`` propagation
    previously inlined in the geometry core, so existing fixtures are
    numerically unchanged. A flagged missing radial velocity propagates as
    zero with :data:`WARN_MISSING_RV` in :attr:`warnings` — never silently.
    """

    provider_id = "linear_astrometry_v1"
    provider_version = "1.0.0"
    epoch_semantics = EPOCH_SEMANTICS_SSB_LIGHT_ARRIVAL
    frame = "icrs"
    origin = "ssb"
    uncertainty_model = "not_propagated"

    def __init__(self, target: Target) -> None:
        self.target = target
        state = target.astrometry
        warnings: list[str] = []
        if state.parallax_mas is not None:
            distance = Distance(parallax=state.parallax_mas * u.mas)
        else:
            assert state.distance_pc is not None
            distance = Distance(state.distance_pc * u.pc)
        radial_velocity = state.radial_velocity_km_s
        if radial_velocity is None:
            warnings.append(WARN_MISSING_RV)
            radial_velocity = 0.0
        reference_epoch = Time(
            state.reference_epoch_jyear,
            format="jyear",
            scale=state.reference_epoch_scale,
        )
        self._catalog = SkyCoord(
            ra=state.ra_deg * u.deg,
            dec=state.dec_deg * u.deg,
            distance=distance,
            pm_ra_cosdec=state.pm_ra_cosdec_mas_per_yr * u.mas / u.yr,
            pm_dec=state.pm_dec_mas_per_yr * u.mas / u.yr,
            radial_velocity=radial_velocity * u.km / u.s,
            obstime=reference_epoch,
            frame="icrs",
        )
        self._warnings = tuple(warnings)
        self._state_cache: OrderedDict[tuple[float, float], TargetState] = OrderedDict()

    @property
    def warnings(self) -> tuple[str, ...]:
        return self._warnings

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "astrometry": self.target.astrometry,
            }
        )

    @property
    def validity_interval_jyear(self) -> tuple[float, float]:
        reference = float(self._catalog.obstime.tdb.jyear)
        return (
            reference - LINEAR_PROPAGATION_SPAN_YEARS,
            reference + LINEAR_PROPAGATION_SPAN_YEARS,
        )

    def state_at(self, epoch: Time) -> TargetState:
        """Propagated state at ``epoch``, memoized per TDB instant (§3.4).

        The memo key is the epoch's two-double TDB Julian date — a
        scientific identity, so equal instants expressed in different
        scales share one computation. Cached states are returned with the
        caller's ``epoch`` object substituted, keeping results
        indistinguishable from an uncached call.
        """
        tdb = epoch.tdb
        key = (float(tdb.jd1), float(tdb.jd2))
        cached = self._state_cache.get(key)
        if cached is not None:
            self._state_cache.move_to_end(key)
            return dataclasses.replace(cached, epoch=epoch)
        state = self._compute_state(epoch)
        self._state_cache[key] = state
        if len(self._state_cache) > STATE_CACHE_MAX:
            self._state_cache.popitem(last=False)
        return state

    def _compute_state(self, epoch: Time) -> TargetState:
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            propagated = self._catalog.apply_space_motion(new_obstime=epoch)
        return TargetState(
            epoch=epoch,
            ra_deg=float(propagated.ra.deg),
            dec_deg=float(propagated.dec.deg),
            distance_au=float(propagated.distance.to_value(u.au)),
            warnings=tuple(f"astropy:{w.message}" for w in caught),
        )

    def states_at(self, epochs: Time) -> tuple[TargetState, ...]:
        """Vectorized propagation: one ``apply_space_motion`` for all epochs.

        Element values are bit-identical to :meth:`state_at` (astropy
        applies the same routines elementwise); call-level astropy warnings
        are attached to every state, conservatively.
        """
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            propagated = self._catalog.apply_space_motion(new_obstime=epochs)
        warnings = tuple(f"astropy:{w.message}" for w in caught)
        ra = np.atleast_1d(np.asarray(propagated.ra.deg, dtype=float))
        dec = np.atleast_1d(np.asarray(propagated.dec.deg, dtype=float))
        distance = np.atleast_1d(
            np.asarray(propagated.distance.to_value(u.au), dtype=float)
        )
        return tuple(
            TargetState(
                epoch=epochs[index],
                ra_deg=float(ra[index]),
                dec_deg=float(dec[index]),
                distance_au=float(distance[index]),
                warnings=warnings,
            )
            for index in range(len(ra))
        )

    def propagation_span_years(self, epoch: Time) -> float:
        return float(abs((epoch - self._catalog.obstime.tdb).to_value(u.yr)))


# ---------------------------------------------------------------------------
# Richer target-state families (registry schema v2)
# ---------------------------------------------------------------------------


def _offset_state(
    base: TargetState, *, d_ra_cosdec_arcsec: float, d_dec_arcsec: float
) -> TargetState:
    """Apply a tangential (on-sky) offset to a propagated state."""
    coord = SkyCoord(ra=base.ra_deg * u.deg, dec=base.dec_deg * u.deg, frame="icrs")
    shifted = coord.spherical_offsets_by(
        d_ra_cosdec_arcsec * u.arcsec, d_dec_arcsec * u.arcsec
    )
    return TargetState(
        epoch=base.epoch,
        ra_deg=float(shifted.ra.deg),
        dec_deg=float(shifted.dec.deg),
        distance_au=base.distance_au,
        warnings=base.warnings,
    )


def _offset_states(
    states: tuple[TargetState, ...],
    d_ra_cosdec_arcsec: np.ndarray,
    d_dec_arcsec: np.ndarray,
) -> tuple[TargetState, ...]:
    """Vectorized tangential offsets: one ``spherical_offsets_by`` call."""
    coords = SkyCoord(
        ra=[state.ra_deg for state in states] * u.deg,
        dec=[state.dec_deg for state in states] * u.deg,
        frame="icrs",
    )
    shifted = coords.spherical_offsets_by(
        np.asarray(d_ra_cosdec_arcsec, dtype=float) * u.arcsec,
        np.asarray(d_dec_arcsec, dtype=float) * u.arcsec,
    )
    ra = np.atleast_1d(np.asarray(shifted.ra.deg, dtype=float))
    dec = np.atleast_1d(np.asarray(shifted.dec.deg, dtype=float))
    return tuple(
        TargetState(
            epoch=state.epoch,
            ra_deg=float(ra[index]),
            dec_deg=float(dec[index]),
            distance_au=state.distance_au,
            warnings=state.warnings,
        )
        for index, state in enumerate(states)
    )


def _eccentric_anomaly(mean_anomaly_rad: float, eccentricity: float) -> float:
    """Solve Kepler's equation E - e sin E = M by Newton-Raphson."""
    mean = math.remainder(mean_anomaly_rad, math.tau)
    ecc_anom = mean if eccentricity < 0.8 else math.copysign(math.pi, mean)
    for _ in range(64):
        delta = (ecc_anom - eccentricity * math.sin(ecc_anom) - mean) / (
            1.0 - eccentricity * math.cos(ecc_anom)
        )
        ecc_anom -= delta
        if abs(delta) < 1e-14:
            return ecc_anom
    raise ValueError(
        f"Kepler solver did not converge for M={mean_anomaly_rad}, e={eccentricity}"
    )


def _relative_orbit_offset_arcsec(
    orbit: OrbitSolution, epoch_jyear: float
) -> tuple[float, float]:
    """(north, east) offset of the secondary from the primary in arcsec.

    Standard visual-binary convention (Campbell elements, position angles
    east of north): in-plane position from the true anomaly, rotated by the
    argument of periastron, inclination, and node.
    """
    mean_anomaly = math.tau * (epoch_jyear - orbit.periastron_epoch_jyear) / orbit.period_yr
    ecc = orbit.eccentricity
    ecc_anom = _eccentric_anomaly(mean_anomaly, ecc)
    true_anom = 2.0 * math.atan2(
        math.sqrt(1.0 + ecc) * math.sin(ecc_anom / 2.0),
        math.sqrt(1.0 - ecc) * math.cos(ecc_anom / 2.0),
    )
    radius = orbit.semimajor_axis_arcsec * (1.0 - ecc * math.cos(ecc_anom))
    lat_arg = math.radians(orbit.arg_periastron_deg) + true_anom
    node = math.radians(orbit.ascending_node_deg)
    cos_incl = math.cos(math.radians(orbit.inclination_deg))
    north = radius * (
        math.cos(lat_arg) * math.cos(node) - math.sin(lat_arg) * math.sin(node) * cos_incl
    )
    east = radius * (
        math.cos(lat_arg) * math.sin(node) + math.sin(lat_arg) * math.cos(node) * cos_incl
    )
    return north, east


class AccelerationAstrometryV1(LinearAstrometryV1):
    """Linear astrometry plus catalog quadratic (acceleration) terms.

    Models catalog acceleration solutions (e.g. Hipparcos-Gaia long-baseline
    or Gaia 7/9-parameter fits): the linear state propagates exactly as in
    ``linear_astrometry_v1`` and the sky-plane offset
    ``0.5 * accel * dt**2`` (about the same reference epoch) is applied
    tangentially.
    """

    provider_id = "acceleration_astrometry_v1"
    provider_version = "1.0.0"

    def __init__(self, target: Target) -> None:
        if target.acceleration is None:
            raise ValueError(
                "acceleration_astrometry_v1 requires a target with acceleration terms"
            )
        super().__init__(target)
        self._acceleration = target.acceleration

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "astrometry": self.target.astrometry,
                "acceleration": self._acceleration,
            }
        )

    def _compute_state(self, epoch: Time) -> TargetState:
        base = super()._compute_state(epoch)
        dt_yr = float((epoch - self._catalog.obstime.tdb).to_value(u.yr))
        half_dt2_yr2 = 0.5 * dt_yr * dt_yr
        return _offset_state(
            base,
            d_ra_cosdec_arcsec=(
                self._acceleration.accel_ra_cosdec_mas_per_yr2 * half_dt2_yr2 / 1000.0
            ),
            d_dec_arcsec=(
                self._acceleration.accel_dec_mas_per_yr2 * half_dt2_yr2 / 1000.0
            ),
        )

    def states_at(self, epochs: Time) -> tuple[TargetState, ...]:
        base_states = super().states_at(epochs)
        dt_yr = np.atleast_1d(
            np.asarray((epochs - self._catalog.obstime.tdb).to_value(u.yr), dtype=float)
        )
        half_dt2_yr2 = 0.5 * dt_yr * dt_yr
        return _offset_states(
            base_states,
            self._acceleration.accel_ra_cosdec_mas_per_yr2 * half_dt2_yr2 / 1000.0,
            self._acceleration.accel_dec_mas_per_yr2 * half_dt2_yr2 / 1000.0,
        )


class TwoBodyOrbitV1(LinearAstrometryV1):
    """Keplerian two-body components about a linearly propagating barycenter.

    The target's catalog astrometry describes the system BARYCENTER, which
    propagates exactly as in ``linear_astrometry_v1``; the published
    relative orbit (secondary about primary, Campbell elements) is scaled by
    the mass fraction to the selected component's orbit about the barycenter
    and applied as a tangential offset. The orbital phase is evaluated at
    the same light-arrival-indexed epoch as the catalog state — the
    convention in which visual-binary periastron epochs are published.

    Declared approximations (beyond the linear barycenter model):
    the orbital line-of-sight displacement and orbital radial velocity are
    neglected, and the angular semimajor axis is held fixed rather than
    rescaled with the slowly changing system distance.
    """

    provider_id = "two_body_orbit_v1"
    provider_version = "1.0.0"
    approximations = (
        "tangential_orbit_offset_only",
        "fixed_angular_semimajor_axis",
        "orbital_radial_velocity_neglected",
    )

    def __init__(self, target: Target) -> None:
        if target.orbit is None:
            raise ValueError("two_body_orbit_v1 requires a target with an orbit solution")
        super().__init__(target)
        self._orbit = target.orbit
        fraction = target.orbit.mass_fraction_secondary
        if target.orbit.component is OrbitComponent.PRIMARY:
            self._offset_factor = -fraction
        elif target.orbit.component is OrbitComponent.SECONDARY:
            self._offset_factor = 1.0 - fraction
        else:
            self._offset_factor = 0.0

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "astrometry": self.target.astrometry,
                "orbit": self._orbit,
            }
        )

    def _compute_state(self, epoch: Time) -> TargetState:
        base = super()._compute_state(epoch)
        if self._offset_factor == 0.0:
            return base
        north, east = _relative_orbit_offset_arcsec(self._orbit, float(epoch.tdb.jyear))
        return _offset_state(
            base,
            d_ra_cosdec_arcsec=east * self._offset_factor,
            d_dec_arcsec=north * self._offset_factor,
        )

    def states_at(self, epochs: Time) -> tuple[TargetState, ...]:
        base_states = super().states_at(epochs)
        if self._offset_factor == 0.0:
            return base_states
        # The Kepler solve is cheap scalar math; only the astropy offset
        # application is worth batching (and matches the scalar path
        # value-for-value because the per-epoch offsets are identical).
        jyears = np.atleast_1d(np.asarray(epochs.tdb.jyear, dtype=float))
        offsets = [
            _relative_orbit_offset_arcsec(self._orbit, float(jyear))
            for jyear in jyears
        ]
        return _offset_states(
            base_states,
            np.array([east * self._offset_factor for _, east in offsets]),
            np.array([north * self._offset_factor for north, _ in offsets]),
        )


class SampledStateV1:
    """Externally generated, checksummed target ephemeris (§2.1).

    The table (:class:`_CartesianEphemerisTable` format) holds barycentric
    ICRS positions of the TARGET endpoint. The registry's astrometry block
    stays the approximate reference solution: at construction the table's
    mid-epoch direction must fall within
    :data:`SampledStateV1.CONSISTENCY_LIMIT_DEG` of the linearly
    propagated astrometry — catching mismatched files while leaving room
    for exactly the departures this family exists to model. Epoch
    semantics are DECLARED by the spec (the v1 geometry model refuses
    non-arrival-indexed tables explicitly); requests outside the tabulated
    span raise :class:`~sglseti.errors.EphemerisCoverageError`, which the
    batch pipeline turns into invalid status rows.
    """

    provider_id = "sampled_state_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    uncertainty_model = "not_propagated"

    #: Maximum allowed mid-epoch separation between the table and the
    #: linearly propagated reference astrometry (a wrong-file guard).
    CONSISTENCY_LIMIT_DEG = 1.0

    def __init__(self, target: Target) -> None:
        if target.sampled_state is None:
            raise ValueError(
                "sampled_state_v1 requires a target with a sampled_state spec"
            )
        spec = target.sampled_state
        self.target = target
        self.epoch_semantics = spec.epoch_semantics
        self._table = _CartesianEphemerisTable(
            spec.path,
            spec.checksum_sha256,
            description="sampled-state ephemeris table",
            coverage_label="sampled-state table",
            owner=f"target {target.target_id!r}",
        )
        mid_jd = 0.5 * float(self._table.epochs_jd[0] + self._table.epochs_jd[-1])
        mid_state = self._state_at_jd(mid_jd)
        reference = LinearAstrometryV1(target).state_at(
            Time(mid_jd, format="jd", scale="tdb")
        )
        separation_deg = math.degrees(
            math.acos(
                min(
                    1.0,
                    max(
                        -1.0,
                        float(
                            np.dot(
                                _radec_unit(mid_state.ra_deg, mid_state.dec_deg),
                                _radec_unit(reference.ra_deg, reference.dec_deg),
                            )
                        ),
                    ),
                )
            )
        )
        if separation_deg > self.CONSISTENCY_LIMIT_DEG:
            raise EphemerisError(
                f"sampled-state ephemeris for target {target.target_id!r} "
                f"points {separation_deg:.2f} deg away from the linearly "
                f"propagated reference astrometry at its mid epoch "
                f"(limit {self.CONSISTENCY_LIMIT_DEG} deg); wrong file?"
            )

    @property
    def warnings(self) -> tuple[str, ...]:
        return ()

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "checksum_sha256": self._table.checksum_sha256,
                "epoch_semantics": self.epoch_semantics,
            }
        )

    @property
    def coverage(self) -> str:
        return self._table.coverage

    @property
    def interpolation(self) -> str:
        return self._table.interpolation

    @property
    def validity_interval_jyear(self) -> tuple[float, float]:
        low, high = self._table.epochs_jd[0], self._table.epochs_jd[-1]
        return (
            2000.0 + (float(low) - 2451545.0) / 365.25,
            2000.0 + (float(high) - 2451545.0) / 365.25,
        )

    def propagation_span_years(self, epoch: Time) -> float | None:
        # No single reference epoch: validity is the tabulated span itself,
        # enforced as hard coverage errors rather than a degraded band.
        return None

    def _state_at_jd(self, jd: float, epoch: Time | None = None) -> TargetState:
        positions, _ = self._table.interpolate(np.array([jd], dtype=float))
        vector = positions[0]
        distance = float(np.linalg.norm(vector))
        ra = math.degrees(math.atan2(float(vector[1]), float(vector[0]))) % 360.0
        dec = math.degrees(math.asin(float(np.clip(vector[2] / distance, -1.0, 1.0))))
        return TargetState(
            epoch=epoch if epoch is not None else Time(jd, format="jd", scale="tdb"),
            ra_deg=ra,
            dec_deg=dec,
            distance_au=distance,
            warnings=(),
        )

    def state_at(self, epoch: Time) -> TargetState:
        return self._state_at_jd(float(epoch.tdb.jd), epoch)

    def states_at(self, epochs: Time) -> tuple[TargetState, ...]:
        jds = np.atleast_1d(np.asarray(epochs.tdb.jd, dtype=float))
        positions, _ = self._table.interpolate(jds)
        distances = np.linalg.norm(positions, axis=1)
        ras = np.degrees(np.arctan2(positions[:, 1], positions[:, 0])) % 360.0
        decs = np.degrees(
            np.arcsin(np.clip(positions[:, 2] / distances, -1.0, 1.0))
        )
        return tuple(
            TargetState(
                epoch=epochs[index],
                ra_deg=float(ras[index]),
                dec_deg=float(decs[index]),
                distance_au=float(distances[index]),
                warnings=(),
            )
            for index in range(len(jds))
        )


def _radec_unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    vector: np.ndarray = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    return vector


# ---------------------------------------------------------------------------
# Baseline observer-state families
# ---------------------------------------------------------------------------


class EarthCenterObserverV1:
    """Earth barycenter position straight from the pinned ephemeris."""

    provider_id = "earth_center_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    time_scale = "tdb"
    interpolation = "none"

    def __init__(self, observer: Observer, ephemeris: Ephemeris) -> None:
        if observer.kind is not ObserverKind.EARTH_CENTER:
            raise ValueError(
                f"earth_center_v1 requires an earth_center observer, "
                f"got kind {observer.kind.value!r}"
            )
        self.observer = observer
        self._ephemeris = ephemeris

    @property
    def coverage(self) -> str | None:
        return None  # bounded only by the ephemeris (coverage errors raise)

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "ephemeris_id": self._ephemeris.ephemeris_id,
            }
        )

    def state_at(self, epoch: Time) -> ObserverState:
        earth = np.asarray(self._ephemeris.earth_barycentric_au(epoch), dtype=float)
        return ObserverState(
            epoch=epoch,
            position_au=(float(earth[0]), float(earth[1]), float(earth[2])),
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        return _positions_matrix(
            self._ephemeris.earth_barycentric_au(epochs), int(epochs.size)
        )


class TerrestrialSiteObserverV1:
    """A fixed terrestrial site: ephemeris Earth barycenter plus the site's
    GCRS position vector treated as an ICRS-axis offset (< 1 mas effect;
    validated against the Phase 0 reference script)."""

    provider_id = "terrestrial_site_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    time_scale = "tdb"
    interpolation = "none"

    def __init__(self, observer: Observer, ephemeris: Ephemeris) -> None:
        if observer.kind is not ObserverKind.SITE:
            raise ValueError(
                f"terrestrial_site_v1 requires a site observer, "
                f"got kind {observer.kind.value!r}"
            )
        assert observer.longitude_deg is not None
        self.observer = observer
        self._ephemeris = ephemeris
        self._location = EarthLocation.from_geodetic(
            lon=observer.longitude_deg * u.deg,
            lat=observer.latitude_deg * u.deg,
            height=observer.height_m * u.m,
        )
        # Per-epoch memo of the (expensive) GCRS site offset (§3.4).
        self._offset_cache: OrderedDict[tuple[float, float], np.ndarray] = OrderedDict()

    @property
    def coverage(self) -> str | None:
        return None  # bounded only by the ephemeris (coverage errors raise)

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "longitude_deg": self.observer.longitude_deg,
                "latitude_deg": self.observer.latitude_deg,
                "height_m": self.observer.height_m,
                "ephemeris_id": self._ephemeris.ephemeris_id,
            }
        )

    def _site_offset_au(self, epoch: Time) -> np.ndarray:
        tdb = epoch.tdb
        key = (float(tdb.jd1), float(tdb.jd2))
        cached = self._offset_cache.get(key)
        if cached is not None:
            self._offset_cache.move_to_end(key)
            return cached
        with offline_resources():
            site_gcrs = self._location.get_gcrs_posvel(epoch)[0]
        offset: np.ndarray = np.asarray(site_gcrs.xyz.to_value(u.au), dtype=float)
        self._offset_cache[key] = offset
        if len(self._offset_cache) > STATE_CACHE_MAX:
            self._offset_cache.popitem(last=False)
        return offset

    def state_at(self, epoch: Time) -> ObserverState:
        earth = np.asarray(self._ephemeris.earth_barycentric_au(epoch), dtype=float)
        position = earth + self._site_offset_au(epoch)
        return ObserverState(
            epoch=epoch,
            position_au=(float(position[0]), float(position[1]), float(position[2])),
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        count = int(epochs.size)
        earth = _positions_matrix(self._ephemeris.earth_barycentric_au(epochs), count)
        with offline_resources():
            site_gcrs = self._location.get_gcrs_posvel(epochs)[0]
        offsets = np.asarray(site_gcrs.xyz.to_value(u.au), dtype=float)
        positions: np.ndarray = earth + _positions_matrix(offsets, count)
        return positions


def _positions_matrix(raw: object, count: int) -> np.ndarray:
    """Normalize an ephemeris position result to shape ``(count, 3)``.

    Accepts a single ``(3,)`` vector (broadcast, e.g. fixture ephemerides),
    the astropy ``(3, count)`` layout, or an already-``(count, 3)`` array.
    When ``count == 3`` the astropy ``(3, count)`` interpretation wins.
    """
    array: np.ndarray = np.asarray(raw, dtype=float)
    if array.ndim == 1:
        broadcast: np.ndarray = np.broadcast_to(array, (count, 3)).copy()
        return broadcast
    if array.shape == (3, count):
        transposed: np.ndarray = np.ascontiguousarray(array.T)
        return transposed
    if array.shape == (count, 3):
        return array
    raise ValueError(
        f"cannot interpret an ephemeris position array of shape {array.shape} "
        f"for {count} epochs"
    )


# ---------------------------------------------------------------------------
# Family resolution
# ---------------------------------------------------------------------------


def _build_target_state_provider(target: Target) -> TargetStateProvider:
    if target.provider_id == AccelerationAstrometryV1.provider_id:
        return AccelerationAstrometryV1(target)
    if target.provider_id == TwoBodyOrbitV1.provider_id:
        return TwoBodyOrbitV1(target)
    if target.provider_id == SampledStateV1.provider_id:
        return SampledStateV1(target)
    return LinearAstrometryV1(target)


def resolve_target_state_provider(target: Target) -> TargetStateProvider:
    """Resolve the target-state provider family declared by ``target``.

    Schema-v1 registry targets are always ``linear_astrometry_v1`` (the
    loader rejects flags the linear family cannot model); schema-v2 targets
    declare their family explicitly, validated by
    :class:`~sglseti.models.Target`.

    Providers are memoized in a bounded LRU keyed by the target's stable
    content hash (§3.4): repeated resolution of scientifically identical
    targets reuses one provider — and its per-epoch state memo — instead
    of rebuilding the catalog coordinate every call. Memoization is pure
    and bit-identical; :func:`clear_provider_cache` resets it.
    """
    key = stable_hash(target)
    provider = _PROVIDER_CACHE.get(key)
    if provider is not None:
        _PROVIDER_CACHE.move_to_end(key)
        _PROVIDER_CACHE_STATS["hits"] += 1
        return provider
    provider = _build_target_state_provider(target)
    _PROVIDER_CACHE_STATS["misses"] += 1
    _PROVIDER_CACHE[key] = provider
    if len(_PROVIDER_CACHE) > PROVIDER_CACHE_MAX:
        _PROVIDER_CACHE.popitem(last=False)
    return provider


# ---------------------------------------------------------------------------
# Provider-backed observer families (roadmap §2.4)
# ---------------------------------------------------------------------------


class SolarSystemBodyObserverV1:
    """A Solar-System body observer from the pinned planetary ephemeris.

    The body name is passed to the calculation's ephemeris resource
    (astropy builtin or pinned JPL kernel); a body the resource cannot
    serve raises :class:`~sglseti.errors.EphemerisError`, and epochs
    outside kernel coverage raise
    :class:`~sglseti.errors.EphemerisCoverageError`.
    """

    provider_id = "solar_system_body_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    time_scale = "tdb"
    interpolation = "none"

    def __init__(self, observer: Observer, ephemeris: Ephemeris) -> None:
        if observer.kind is not ObserverKind.SOLAR_SYSTEM_BODY:
            raise ValueError(
                f"solar_system_body_v1 requires a solar_system_body observer, "
                f"got kind {observer.kind.value!r}"
            )
        assert observer.body is not None
        self.observer = observer
        self._body = observer.body
        self._ephemeris = ephemeris

    @property
    def coverage(self) -> str | None:
        return None  # bounded only by the ephemeris (coverage errors raise)

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "body": self._body,
                "ephemeris_id": self._ephemeris.ephemeris_id,
            }
        )

    def state_at(self, epoch: Time) -> ObserverState:
        position = np.asarray(
            self._ephemeris.body_barycentric_au(self._body, epoch), dtype=float
        )
        return ObserverState(
            epoch=epoch,
            position_au=(float(position[0]), float(position[1]), float(position[2])),
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        return _positions_matrix(
            self._ephemeris.body_barycentric_au(self._body, epochs), int(epochs.size)
        )


class _CartesianEphemerisTable:
    """Shared checksummed-ECSV machinery for sampled cartesian ephemerides.

    Backs both ``spacecraft_table_v1`` (observer positions) and
    ``sampled_state_v1`` (target positions): columns ``epoch_tdb_jd``
    (strictly increasing), ``x_au``/``y_au``/``z_au`` (barycentric ICRS),
    and optionally ``vx_au_per_day``/``vy_au_per_day``/``vz_au_per_day``.
    Interpolation is cubic Hermite when velocities are present, linear
    otherwise; requests outside the tabulated span raise
    :class:`~sglseti.errors.EphemerisCoverageError`. Files are identified
    by SHA-256 content checksum; a pinned checksum makes a mismatch a hard
    error.
    """

    _COLUMNS = ("epoch_tdb_jd", "x_au", "y_au", "z_au")
    _VELOCITY_COLUMNS = ("vx_au_per_day", "vy_au_per_day", "vz_au_per_day")

    def __init__(
        self,
        path_str: str,
        pinned_checksum: str | None,
        *,
        description: str,
        coverage_label: str,
        owner: str,
    ) -> None:
        path = Path(path_str)
        if not path.is_file():
            raise EphemerisError(f"{description} not found: {path}")
        self.checksum_sha256 = file_sha256(path)
        if pinned_checksum is not None and pinned_checksum != self.checksum_sha256:
            raise EphemerisError(
                f"{description} checksum mismatch for {path.name}: "
                f"expected {pinned_checksum}, got {self.checksum_sha256}"
            )
        from astropy.table import Table

        try:
            table = Table.read(path, format="ascii.ecsv")
        except Exception as exc:
            raise EphemerisError(
                f"failed to parse {description} {path.name}: {exc}"
            ) from exc
        missing = [name for name in self._COLUMNS if name not in table.colnames]
        if missing:
            raise EphemerisError(f"{description} {path.name} lacks columns {missing}")
        self.epochs_jd = np.asarray(table["epoch_tdb_jd"], dtype=float)
        self.positions = np.column_stack(
            [np.asarray(table[name], dtype=float) for name in self._COLUMNS[1:]]
        )
        has_velocities = all(name in table.colnames for name in self._VELOCITY_COLUMNS)
        self.velocities = (
            np.column_stack(
                [np.asarray(table[name], dtype=float) for name in self._VELOCITY_COLUMNS]
            )
            if has_velocities
            else None
        )
        if len(self.epochs_jd) < 2:
            raise EphemerisError(f"{description} {path.name} needs at least two rows")
        if not np.all(np.isfinite(self.epochs_jd)) or not np.all(
            np.isfinite(self.positions)
        ):
            raise EphemerisError(
                f"{description} {path.name} contains non-finite values"
            )
        if np.any(np.diff(self.epochs_jd) <= 0.0):
            raise EphemerisError(
                f"{description} {path.name} epochs must be strictly increasing"
            )
        self.interpolation = "cubic_hermite" if has_velocities else "linear"
        self._coverage_label = coverage_label
        self._owner = owner

    @property
    def coverage(self) -> str:
        return f"tdb_jd [{self.epochs_jd[0]:.6f}, {self.epochs_jd[-1]:.6f}]"

    def interpolate(self, jds: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
        low, high = self.epochs_jd[0], self.epochs_jd[-1]
        if np.any(jds < low) or np.any(jds > high):
            raise EphemerisCoverageError(
                f"epoch(s) outside {self._coverage_label} coverage "
                f"{self.coverage} for {self._owner}"
            )
        index = np.clip(
            np.searchsorted(self.epochs_jd, jds, side="right") - 1,
            0,
            len(self.epochs_jd) - 2,
        )
        t0 = self.epochs_jd[index]
        step = self.epochs_jd[index + 1] - t0
        s = ((jds - t0) / step)[:, np.newaxis]
        p0 = self.positions[index]
        p1 = self.positions[index + 1]
        if self.velocities is None:
            return p0 * (1.0 - s) + p1 * s, None
        h = step[:, np.newaxis]
        v0 = self.velocities[index] * h
        v1 = self.velocities[index + 1] * h
        h00 = 2 * s**3 - 3 * s**2 + 1
        h10 = s**3 - 2 * s**2 + s
        h01 = -2 * s**3 + 3 * s**2
        h11 = s**3 - s**2
        positions = h00 * p0 + h10 * v0 + h01 * p1 + h11 * v1
        d00 = 6 * s**2 - 6 * s
        d10 = 3 * s**2 - 4 * s + 1
        d01 = -6 * s**2 + 6 * s
        d11 = 3 * s**2 - 2 * s
        velocities = (d00 * p0 + d10 * v0 + d01 * p1 + d11 * v1) / h
        return positions, velocities


class TabularSpacecraftObserverV1:
    """A spacecraft observer from a checksummed tabular ephemeris (§2.4).

    Table format, interpolation policy, and coverage behavior per
    :class:`_CartesianEphemerisTable`. The file is identified by SHA-256
    content checksum (a pinned spec checksum makes a mismatch a hard
    error); identities never carry the path.
    """

    provider_id = "spacecraft_table_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    time_scale = "tdb"

    def __init__(self, observer: Observer, ephemeris: Ephemeris | None = None) -> None:
        del ephemeris  # tabulated positions are independent of the ephemeris
        if observer.kind is not ObserverKind.SPACECRAFT_TABLE:
            raise ValueError(
                f"spacecraft_table_v1 requires a spacecraft_table observer, "
                f"got kind {observer.kind.value!r}"
            )
        assert observer.path is not None
        self._table = _CartesianEphemerisTable(
            observer.path,
            observer.checksum_sha256,
            description="spacecraft ephemeris table",
            coverage_label="spacecraft table",
            owner=f"observer {observer.observer_id!r}",
        )
        self.observer = observer
        self.checksum_sha256 = self._table.checksum_sha256
        self.interpolation = self._table.interpolation

    @property
    def coverage(self) -> str:
        return self._table.coverage

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "checksum_sha256": self.checksum_sha256,
            }
        )

    def state_at(self, epoch: Time) -> ObserverState:
        positions, velocities = self._table.interpolate(
            np.array([float(epoch.tdb.jd)], dtype=float)
        )
        velocity = (
            None
            if velocities is None
            else (
                float(velocities[0, 0]),
                float(velocities[0, 1]),
                float(velocities[0, 2]),
            )
        )
        return ObserverState(
            epoch=epoch,
            position_au=(
                float(positions[0, 0]),
                float(positions[0, 1]),
                float(positions[0, 2]),
            ),
            velocity_au_per_day=velocity,
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        positions, _ = self._table.interpolate(
            np.atleast_1d(np.asarray(epochs.tdb.jd, dtype=float))
        )
        return positions


class SpiceSpacecraftObserverV1:
    """A spacecraft observer from a SPICE SPK kernel (optional spiceypy).

    Positions are evaluated with ``spkgeo`` (geometric states, observer =
    Solar-System barycenter) in the SPICE ``J2000`` frame — offset from
    ICRS by the constant ~17 mas frame bias, a declared approximation far
    below any v1 pointing tolerance. Epoch conversion (TDB seconds past
    J2000) is computed from astropy, so no leap-second kernel is needed.
    The SPK file is identified by content checksum, never path; epochs
    outside its coverage raise
    :class:`~sglseti.errors.EphemerisCoverageError`.
    """

    provider_id = "spacecraft_spice_v1"
    provider_version = "1.0.0"
    frame = "icrs"  # SPICE J2000; ~17 mas frame bias declared above
    origin = "ssb"
    time_scale = "tdb"
    interpolation = "spk_segment"

    _KM_PER_AU = 149_597_870.700

    def __init__(self, observer: Observer, ephemeris: Ephemeris | None = None) -> None:
        del ephemeris  # SPK states are independent of the planetary ephemeris
        if observer.kind is not ObserverKind.SPACECRAFT_SPICE:
            raise ValueError(
                f"spacecraft_spice_v1 requires a spacecraft_spice observer, "
                f"got kind {observer.kind.value!r}"
            )
        assert observer.path is not None
        assert observer.spice_target is not None
        try:
            import spiceypy  # type: ignore[import-untyped]
        except ImportError as exc:
            raise EphemerisError(
                "the spacecraft_spice observer requires the optional "
                "'spiceypy' dependency"
            ) from exc
        self._spice = spiceypy
        path = Path(observer.path)
        if not path.is_file():
            raise EphemerisError(f"SPICE kernel not found: {path}")
        self.checksum_sha256 = file_sha256(path)
        if (
            observer.checksum_sha256 is not None
            and observer.checksum_sha256 != self.checksum_sha256
        ):
            raise EphemerisError(
                f"SPICE kernel checksum mismatch for {path.name}: "
                f"expected {observer.checksum_sha256}, got {self.checksum_sha256}"
            )
        target = observer.spice_target.strip()
        try:
            self._target_id = int(target)
        except ValueError:
            try:
                self._target_id = int(spiceypy.bods2c(target))
            except Exception as exc:
                raise EphemerisError(
                    f"unknown SPICE target {target!r}: {exc}"
                ) from exc
        try:
            self._handle = spiceypy.spklef(str(path))
            cell = spiceypy.cell_double(200)
            spiceypy.spkcov(str(path), self._target_id, cell)
            windows = [
                spiceypy.wnfetd(cell, i) for i in range(spiceypy.wncard(cell))
            ]
        except Exception as exc:
            raise EphemerisError(
                f"failed to load SPICE kernel {path.name} for target "
                f"{self._target_id}: {exc}"
            ) from exc
        if not windows:
            raise EphemerisError(
                f"SPICE kernel {path.name} has no coverage for target "
                f"{self._target_id}"
            )
        self._windows_et = windows
        self.observer = observer

    @property
    def coverage(self) -> str:
        spans = ", ".join(
            f"[{2451545.0 + a / 86400.0:.6f}, {2451545.0 + b / 86400.0:.6f}]"
            for a, b in self._windows_et
        )
        return f"tdb_jd {spans}"

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "spice_target": self._target_id,
                "checksum_sha256": self.checksum_sha256,
            }
        )

    def _et(self, epoch: Time) -> float:
        tdb = epoch.tdb
        return ((float(tdb.jd1) - 2451545.0) + float(tdb.jd2)) * 86400.0

    def state_at(self, epoch: Time) -> ObserverState:
        et = self._et(epoch)
        if not any(a <= et <= b for a, b in self._windows_et):
            raise EphemerisCoverageError(
                f"epoch {epoch.isot} is outside the SPICE coverage "
                f"{self.coverage} for observer {self.observer.observer_id!r}"
            )
        try:
            state, _light_time = self._spice.spkgeo(
                targ=self._target_id, et=et, ref="J2000", obs=0
            )
        except Exception as exc:
            raise EphemerisCoverageError(
                f"SPICE evaluation failed at {epoch.isot} for observer "
                f"{self.observer.observer_id!r}: {exc}"
            ) from exc
        position = tuple(float(v) / self._KM_PER_AU for v in state[:3])
        velocity = tuple(
            float(v) * 86400.0 / self._KM_PER_AU for v in state[3:6]
        )
        return ObserverState(
            epoch=epoch,
            position_au=(position[0], position[1], position[2]),
            velocity_au_per_day=(velocity[0], velocity[1], velocity[2]),
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        positions: np.ndarray = np.array(
            [self.state_at(epochs[index]).position_au for index in range(epochs.size)]
        )
        return positions


#: Registered state functions backing programmatic observers, keyed by
#: observer_id. Registration is an explicit integration hook, not hidden
#: state: a request naming a programmatic observer fails loudly unless the
#: process registered its function first.
_PROGRAMMATIC_OBSERVERS: dict[str, Callable[[Time], np.ndarray]] = {}


def register_programmatic_observer(
    observer_id: str, position_fn: Callable[[Time], np.ndarray]
) -> None:
    """Register the state function backing a programmatic observer (§2.4).

    ``position_fn(time)`` must return the barycentric ICRS position in AU
    (array-like of 3). The matching :class:`~sglseti.models.Observer`
    spec's ``identity`` string is the caller-DECLARED content identity of
    this function: change it whenever the function's science changes, or
    calculation IDs will wrongly collide. Re-registering an ID replaces
    the function and clears the observer-provider memo.
    """
    _PROGRAMMATIC_OBSERVERS[observer_id] = position_fn
    _OBSERVER_CACHE.clear()


def unregister_programmatic_observer(observer_id: str) -> None:
    """Remove a registered programmatic observer state function."""
    _PROGRAMMATIC_OBSERVERS.pop(observer_id, None)
    _OBSERVER_CACHE.clear()


class ProgrammaticObserverV1:
    """A caller-supplied observer state function, for tests and integrations."""

    provider_id = "programmatic_observer_v1"
    provider_version = "1.0.0"
    frame = "icrs"
    origin = "ssb"
    time_scale = "tdb"
    interpolation = "programmatic"

    def __init__(self, observer: Observer, ephemeris: Ephemeris | None = None) -> None:
        del ephemeris
        if observer.kind is not ObserverKind.PROGRAMMATIC:
            raise ValueError(
                f"programmatic_observer_v1 requires a programmatic observer, "
                f"got kind {observer.kind.value!r}"
            )
        function = _PROGRAMMATIC_OBSERVERS.get(observer.observer_id)
        if function is None:
            raise GenerationError(
                f"programmatic observer {observer.observer_id!r} has no "
                "registered state function; call "
                "register_programmatic_observer() first"
            )
        self.observer = observer
        self._function = function

    @property
    def coverage(self) -> str | None:
        return None  # declared by the registered function's owner

    @cached_property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "observer_id": self.observer.observer_id,
                "identity": self.observer.identity,
            }
        )

    def state_at(self, epoch: Time) -> ObserverState:
        position = np.asarray(self._function(epoch), dtype=float)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            raise GenerationError(
                f"programmatic observer {self.observer.observer_id!r} returned "
                f"an invalid position {position!r}; expected 3 finite AU values"
            )
        return ObserverState(
            epoch=epoch,
            position_au=(float(position[0]), float(position[1]), float(position[2])),
        )

    def positions_au(self, epochs: Time) -> np.ndarray:
        positions: np.ndarray = np.array(
            [self.state_at(epochs[index]).position_au for index in range(epochs.size)]
        )
        return positions


_OBSERVER_CACHE: OrderedDict[tuple[str, str | None, int], ObserverStateProvider] = (
    OrderedDict()
)
_OBSERVER_CACHE_MAX = 16

_OBSERVER_FAMILIES: dict[ObserverKind, type] = {
    ObserverKind.EARTH_CENTER: EarthCenterObserverV1,
    ObserverKind.SITE: TerrestrialSiteObserverV1,
    ObserverKind.SOLAR_SYSTEM_BODY: SolarSystemBodyObserverV1,
    ObserverKind.SPACECRAFT_TABLE: TabularSpacecraftObserverV1,
    ObserverKind.SPACECRAFT_SPICE: SpiceSpacecraftObserverV1,
    ObserverKind.PROGRAMMATIC: ProgrammaticObserverV1,
}


def resolve_observer_state_provider(
    observer: Observer, ephemeris: Ephemeris
) -> ObserverStateProvider:
    """Resolve the observer-state provider family declared by ``observer``.

    Memoized per (observer content hash, observer path, ephemeris OBJECT)
    so file loads, GCRS memos, and SPK handles survive across calls. The
    path enters the key because the canonical observer form is
    deliberately path-free; the ephemeris part is object identity,
    deliberately conservative (fixture ephemerides can share an
    ``ephemeris_id`` while returning different positions). Cleared by
    :func:`clear_provider_cache`.
    """
    key = (stable_hash(observer), observer.path, id(ephemeris))
    provider = _OBSERVER_CACHE.get(key)
    if provider is not None:
        _OBSERVER_CACHE.move_to_end(key)
        return provider
    built: ObserverStateProvider = _OBSERVER_FAMILIES[observer.kind](
        observer, ephemeris
    )
    provider = built
    _OBSERVER_CACHE[key] = provider
    if len(_OBSERVER_CACHE) > _OBSERVER_CACHE_MAX:
        _OBSERVER_CACHE.popitem(last=False)
    return provider
