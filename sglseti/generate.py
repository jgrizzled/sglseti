"""Epoch-neutral batch calculation orchestration.

:func:`generate_loci` forms the deterministic product

    targets (request order) x roles (request order) x epochs (input order)
    x relay segments (ascending distance)

and emits one :class:`~sglseti.models.LocusSample` per combination plus one
:class:`~sglseti.models.Corridor` per target/role/epoch. That iteration
order IS the documented output order; it never depends on registry mapping
order, wall-clock time, or file locations. The generator does not know or
care whether an epoch is historical or future.

Failure isolation: an ephemeris-coverage failure yields an ``invalid``
status row (NaN coordinates, machine-readable reason code) for that
combination only — valid rows from unrelated combinations are always kept.
``strict=True`` instead fails the whole batch on the first invalid result.

Identity (plan §4.4): ``calculation_id`` covers the normalized request
(ephemeris identified by content checksum, never path), the model identity,
and the astrometric record hashes of exactly the requested targets.

Memory stays bounded by the output itself: rows are produced by streaming
iteration, never by materializing intermediate per-combination products.
For archive-scale runs (§3.4), :func:`plan_calculation` resolves the
deterministic execution plan up front and :func:`iter_locus_chunks` yields
one :class:`LocusChunk` per target/role/epoch — in exactly the documented
product order, sliceable by chunk index — without materializing the full
result. A chunk is independently reproducible: re-running any index range
of the same plan produces identical corridors with the same
``calculation_id``, so parallel execution can remain a downstream
orchestration concern.
"""

from __future__ import annotations

import math
import warnings as _warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .ephemeris import (
    WARN_IERS_COVERAGE,
    AstropyEphemeris,
    Ephemeris,
    IersResource,
    bundled_iers_id,
)
from .errors import EphemerisCoverageError, GenerationError
from .geometry import (
    C_AU_PER_DAY,
    GeometryModel,
    RelaySolution,
    Tusay2022Eq57V1,
    altaz_apparent,
    cirs_apparent,
    compute_relay_solution,
    motion_rates,
)
from .models import (
    CalculationResult,
    CoordinateProduct,
    Corridor,
    Epoch,
    GeometryRequest,
    LocusSample,
    RangeSegment,
    Role,
    Target,
    TargetEventKind,
    TimeGrid,
    TimeIntervals,
    TimeList,
    TimeSingle,
    TimeSpec,
    UncertaintyMethod,
    Validity,
)
from .provenance import canonicalize, stable_hash, stable_id
from .providers import (
    resolve_observer_state_provider,
    resolve_target_state_provider,
)
from .sampling import generate_segments
from .targets import TargetRegistry

__all__ = [
    "MAX_MATERIALIZED_EPOCHS",
    "RATE_STEP_S",
    "CalculationPlan",
    "LocusChunk",
    "generate_loci",
    "iter_locus_chunks",
    "materialize_epochs",
    "plan_calculation",
]

#: Finite-difference step for locus angular rates (recorded in manifests).
RATE_STEP_S = 60.0

#: Backstop for API-constructed grids (config enforces the same bound for
#: file-loaded requests).
MAX_MATERIALIZED_EPOCHS = 1_000_000

WARN_EPHEMERIS_COVERAGE = "ephemeris_out_of_coverage"
WARN_UNCERTAINTY_NOT_PROPAGATED = "uncertainty_not_propagated"

_MODEL_REGISTRY: dict[str, type[GeometryModel]] = {
    Tusay2022Eq57V1.model_id: Tusay2022Eq57V1,
}

# Role -> physical target-event kind, used when a failed combination must
# still be labeled without a computed DirectionSolution.
_ROLE_EVENT_KIND = {
    Role.ANTIPODE: TargetEventKind.APPARENT_STATE,
    Role.RX: TargetEventKind.EMISSION,
    Role.TX: TargetEventKind.ARRIVAL,
}


def materialize_epochs(time_spec: TimeSpec) -> tuple[Epoch, ...]:
    """Expand a validated time specification into concrete epochs.

    Grid epochs get deterministic IDs ``grid-000000``, ``grid-000001``, …
    in ascending time order; list and single modes keep caller IDs;
    observation intervals expand to their labeled sample times with IDs
    ``<interval_id>@<phase>`` and the interval linkage carried on each
    epoch (and so onto every product row).
    """
    if isinstance(time_spec, TimeSingle):
        return (time_spec.epoch,)
    if isinstance(time_spec, TimeList):
        return time_spec.epochs
    if isinstance(time_spec, TimeIntervals):
        epochs: list[Epoch] = []
        for interval in time_spec.intervals:
            for phase, time in interval.labeled_sample_times():
                epochs.append(
                    Epoch(
                        epoch_id=f"{interval.interval_id}@{phase}",
                        time=time,
                        metadata=interval.metadata,
                        interval_id=interval.interval_id,
                        interval_phase=phase,
                        interval_duration_s=interval.duration_s,
                    )
                )
        if len(epochs) > MAX_MATERIALIZED_EPOCHS:
            raise GenerationError(
                f"intervals would materialize {len(epochs)} epochs; "
                f"limit is {MAX_MATERIALIZED_EPOCHS}"
            )
        return tuple(epochs)
    assert isinstance(time_spec, TimeGrid)
    from astropy.time import TimeDelta

    duration_s = float((time_spec.stop - time_spec.start).sec)
    # Microsecond tolerance keeps an exactly-on-grid stop time inclusive
    # despite floating-point Time arithmetic.
    count = math.floor((duration_s + 1e-6) / time_spec.cadence_s) + 1
    if count > MAX_MATERIALIZED_EPOCHS:
        raise GenerationError(
            f"grid would materialize {count} epochs; limit is {MAX_MATERIALIZED_EPOCHS}"
        )
    return tuple(
        Epoch(
            epoch_id=f"grid-{index:06d}",
            time=time_spec.start + TimeDelta(index * time_spec.cadence_s, format="sec"),
        )
        for index in range(count)
    )


@dataclass(frozen=True)
class CalculationPlan:
    """The resolved, deterministic execution plan of one request (§3.4).

    Everything :func:`iter_locus_chunks` needs — resolved model and
    ephemeris, materialized epochs, target hashes, Earth-orientation
    resource, and the ``calculation_id`` — computed once so chunked and
    batch execution share one identity and one code path.
    ``chunk_count`` is ``targets x roles x epochs``.
    """

    request: GeometryRequest
    calculation_id: str
    chunk_count: int
    epochs: tuple[Epoch, ...]
    targets: tuple[Target, ...]
    target_hashes: Mapping[str, str]
    model: GeometryModel
    ephemeris: Ephemeris
    iers_resource: IersResource | None
    iers_id: str | None
    uncertainty_method: UncertaintyMethod
    want_cirs: bool
    want_altaz: bool
    #: (provider_id, provider_version, content_hash) per target and for the
    #: observer — recorded on every product row (§3.5).
    target_provider_identities: Mapping[str, tuple[str, str, str]]
    observer_provider_identity: tuple[str, str, str]


@dataclass(frozen=True)
class LocusChunk:
    """One deterministic unit of chunked execution: a full corridor.

    ``chunk_index`` enumerates the documented product order (targets x
    roles x epochs); the corridor carries the shared ``calculation_id``,
    so any index range recomputed later (or elsewhere) is byte-identical
    to the same range of the full run.
    """

    chunk_index: int
    chunk_count: int
    corridor: Corridor
    invalid_count: int
    degraded_count: int


def plan_calculation(
    request: GeometryRequest,
    registry: TargetRegistry,
    *,
    model: GeometryModel | None = None,
    ephemeris: Ephemeris | None = None,
) -> CalculationPlan:
    """Resolve a request into its deterministic execution plan.

    ``model`` and ``ephemeris`` default to what the request specifies and
    exist as parameters for testing with deterministic fakes.
    """
    unknown = [tid for tid in request.target_ids if tid not in registry]
    if unknown:
        raise GenerationError(
            f"unknown target ID(s) {unknown}; registry contains {sorted(registry.ids)}"
        )
    if model is None:
        model = _MODEL_REGISTRY[request.model_id]()
    if ephemeris is None:
        ephemeris = AstropyEphemeris(request.ephemeris)

    epochs = materialize_epochs(request.time)
    targets = tuple(registry[tid] for tid in request.target_ids)
    target_hashes = {target.target_id: stable_hash(target) for target in targets}

    want_cirs = CoordinateProduct.CIRS in request.coordinate_products
    want_altaz = CoordinateProduct.ALTAZ in request.coordinate_products
    # Earth orientation only touches apparent and site-visibility products;
    # its identity enters the calculation ID exactly when those exist.
    iers_sensitive = want_cirs or want_altaz or request.observability is not None
    iers_resource = (
        IersResource(request.iers)
        if request.iers is not None and iers_sensitive
        else None
    )
    iers_id = (
        (iers_resource.iers_id if iers_resource else bundled_iers_id())
        if iers_sensitive
        else None
    )
    calculation_id = _calculation_id(
        request, model, ephemeris, target_hashes, iers_id
    )
    uncertainty_method = (
        UncertaintyMethod.ASSUMED
        if request.assumed_half_width_arcsec is not None
        else UncertaintyMethod.NOT_PROPAGATED
    )
    target_provider_identities = {}
    for target in targets:
        provider = resolve_target_state_provider(target)
        target_provider_identities[target.target_id] = (
            provider.provider_id,
            provider.provider_version,
            provider.content_hash,
        )
    observer_provider = resolve_observer_state_provider(request.observer, ephemeris)
    observer_provider_identity = (
        observer_provider.provider_id,
        observer_provider.provider_version,
        observer_provider.content_hash,
    )
    return CalculationPlan(
        request=request,
        calculation_id=calculation_id,
        chunk_count=len(targets) * len(request.roles) * len(epochs),
        epochs=epochs,
        targets=targets,
        target_hashes=target_hashes,
        model=model,
        ephemeris=ephemeris,
        iers_resource=iers_resource,
        iers_id=iers_id,
        uncertainty_method=uncertainty_method,
        want_cirs=want_cirs,
        want_altaz=want_altaz,
        target_provider_identities=target_provider_identities,
        observer_provider_identity=observer_provider_identity,
    )


def iter_locus_chunks(
    request: GeometryRequest,
    registry: TargetRegistry,
    *,
    plan: CalculationPlan | None = None,
    model: GeometryModel | None = None,
    ephemeris: Ephemeris | None = None,
    strict: bool = False,
    start: int = 0,
    stop: int | None = None,
) -> Iterator[LocusChunk]:
    """Yield corridors one chunk at a time, never the full result (§3.4).

    Chunks arrive in the documented product order; ``start``/``stop``
    select a chunk-index range of the SAME full calculation (identities
    unchanged), which is how a downstream orchestrator distributes work.
    Pass a precomputed ``plan`` to skip re-resolution; it must belong to
    this request.
    """
    if plan is None:
        plan = plan_calculation(request, registry, model=model, ephemeris=ephemeris)
    elif plan.request != request:
        raise GenerationError("the supplied plan was built for a different request")
    if start < 0 or (stop is not None and stop < start):
        raise GenerationError(
            f"invalid chunk range [{start}, {stop}); chunk_count is {plan.chunk_count}"
        )
    yield from _iter_chunks(plan, strict=strict, start=start, stop=stop)


def _iter_chunks(
    plan: CalculationPlan, *, strict: bool, start: int, stop: int | None
) -> Iterator[LocusChunk]:
    request = plan.request
    index = -1
    for target in plan.targets:
        for role in request.roles:
            segments = None
            for epoch in plan.epochs:
                index += 1
                if index < start:
                    continue
                if stop is not None and index >= stop:
                    return
                if segments is None:
                    segments = generate_segments(
                        target_id=target.target_id,
                        role=role,
                        relay_range=request.relay_range,
                        sampling=request.sampling,
                    )
                corridor_samples: list[LocusSample] = []
                invalid_count = 0
                degraded_count = 0
                for segment in segments:
                    sample = _compute_sample(
                        request=request,
                        target=target,
                        role=role,
                        epoch=epoch,
                        segment=segment,
                        model=plan.model,
                        ephemeris=plan.ephemeris,
                        calculation_id=plan.calculation_id,
                        target_source_hash=plan.target_hashes[target.target_id],
                        uncertainty_method=plan.uncertainty_method,
                        want_cirs=plan.want_cirs,
                        want_altaz=plan.want_altaz,
                        iers_resource=plan.iers_resource,
                        target_provider=plan.target_provider_identities[
                            target.target_id
                        ],
                        observer_provider=plan.observer_provider_identity,
                    )
                    if sample.validity is Validity.INVALID:
                        invalid_count += 1
                        if strict:
                            raise GenerationError(
                                "strict mode: invalid sample for "
                                f"target={sample.target_id} role={sample.role} "
                                f"epoch={sample.epoch_id} z={sample.z_au} AU "
                                f"(warnings: {', '.join(sample.warnings)})"
                            )
                    elif sample.validity is Validity.DEGRADED:
                        degraded_count += 1
                    corridor_samples.append(sample)
                corridor = _build_corridor(
                    request=request,
                    calculation_id=plan.calculation_id,
                    target=target,
                    role=role,
                    epoch=epoch,
                    corridor_samples=tuple(corridor_samples),
                    uncertainty_method=plan.uncertainty_method,
                )
                yield LocusChunk(
                    chunk_index=index,
                    chunk_count=plan.chunk_count,
                    corridor=corridor,
                    invalid_count=invalid_count,
                    degraded_count=degraded_count,
                )


def generate_loci(
    request: GeometryRequest,
    registry: TargetRegistry,
    *,
    model: GeometryModel | None = None,
    ephemeris: Ephemeris | None = None,
    strict: bool = False,
) -> CalculationResult:
    """Run the batch calculation for a validated request.

    ``model`` and ``ephemeris`` default to what the request specifies and
    exist as parameters for testing with deterministic fakes; passing a
    different scientific configuration than the request describes is the
    caller's responsibility to record. Built on :func:`iter_locus_chunks`,
    so batch and chunked execution share one code path and one identity.
    """
    plan = plan_calculation(request, registry, model=model, ephemeris=ephemeris)

    samples: list[LocusSample] = []
    corridors: list[Corridor] = []
    invalid_count = 0
    degraded_count = 0
    for chunk in _iter_chunks(plan, strict=strict, start=0, stop=None):
        corridors.append(chunk.corridor)
        samples.extend(chunk.corridor.samples)
        invalid_count += chunk.invalid_count
        degraded_count += chunk.degraded_count

    warnings: list[str] = []
    if plan.uncertainty_method is UncertaintyMethod.NOT_PROPAGATED:
        warnings.append(WARN_UNCERTAINTY_NOT_PROPAGATED)
    if invalid_count:
        warnings.append(f"invalid_sample_count:{invalid_count}")
    if degraded_count:
        warnings.append(f"degraded_sample_count:{degraded_count}")

    return CalculationResult(
        calculation_id=plan.calculation_id,
        request=request,
        samples=tuple(samples),
        corridors=tuple(corridors),
        warnings=tuple(warnings),
        iers_id=plan.iers_id,
    )


def _calculation_id(
    request: GeometryRequest,
    model: GeometryModel,
    ephemeris: Ephemeris,
    target_hashes: dict[str, str],
    iers_id: str | None,
) -> str:
    canonical_request = canonicalize(request)
    # File-backed resources contribute their content identity, never their
    # location: replace the specs (which may carry paths) wholesale. The
    # IERS identity is None for requests without apparent/site products, so
    # purely geometric IDs never churn with Earth-orientation releases.
    canonical_request["fields"]["ephemeris"] = ephemeris.ephemeris_id
    canonical_request["fields"]["iers"] = iers_id
    return stable_id(
        "calc",
        {
            "request": canonical_request,
            "model": {"id": model.model_id, "version": model.model_version},
            "target_source_hashes": dict(sorted(target_hashes.items())),
            "ephemeris_id": ephemeris.ephemeris_id,
            "iers_id": iers_id,
        },
    )


def _sample_id(segment: RangeSegment) -> str:
    return stable_id("smp", {"segment_id": segment.segment_id, "z_au": segment.z_rep_au})


def _compute_sample(
    *,
    request: GeometryRequest,
    target: Target,
    role: Role,
    epoch: Epoch,
    segment: RangeSegment,
    model: GeometryModel,
    ephemeris: Ephemeris,
    calculation_id: str,
    target_source_hash: str,
    uncertainty_method: UncertaintyMethod,
    want_cirs: bool,
    want_altaz: bool,
    iers_resource: IersResource | None,
    target_provider: tuple[str, str, str],
    observer_provider: tuple[str, str, str],
) -> LocusSample:
    z_au = segment.z_rep_au

    def _solve(at_z_au: float) -> RelaySolution:
        return compute_relay_solution(
            target=target,
            observation_time=epoch.time,
            z_au=at_z_au,
            role=role,
            observer=request.observer,
            ephemeris=ephemeris,
            model=model,
        )

    try:
        solution = _solve(z_au)
        # Interval boundaries: the segment represents [z_near, z_far], and a
        # pointing footprint must cover those extremes, not just z_rep.
        if segment.is_point:
            near_solution = far_solution = solution
        else:
            near_solution = _solve(segment.z_near_au)
            far_solution = _solve(segment.z_far_au)
    except EphemerisCoverageError as exc:
        return _invalid_sample(
            request=request,
            target=target,
            role=role,
            epoch=epoch,
            segment=segment,
            calculation_id=calculation_id,
            target_source_hash=target_source_hash,
            ephemeris_id=ephemeris.ephemeris_id,
            model=model,
            uncertainty_method=uncertainty_method,
            target_provider=target_provider,
            observer_provider=observer_provider,
            reason=f"{WARN_EPHEMERIS_COVERAGE}: {exc}",
        )

    # Apparent products depend on Earth orientation: capture transform
    # warnings (extrapolated polar motion/UT1, dubious ERFA years) into the
    # sample instead of letting them evaporate at the console, and pre-check
    # a pinned table's coverage deterministically.
    apparent_warnings: list[str] = []
    cirs: tuple[float | None, float | None] = (None, None)
    altaz: tuple[float | None, float | None] = (None, None)
    if want_cirs or want_altaz:
        iers_table = iers_resource.table if iers_resource is not None else None
        if iers_resource is not None and not iers_resource.covers(epoch.time):
            apparent_warnings.append(WARN_IERS_COVERAGE)
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            if want_cirs:
                cirs = cirs_apparent(solution, iers_table=iers_table)
            if want_altaz:
                altaz = altaz_apparent(solution, iers_table=iers_table)
        apparent_warnings.extend(
            dict.fromkeys(f"astropy:{w.message}" for w in caught)
        )
    rates = None
    near_rates = None
    if request.include_rates:
        rates = motion_rates(
            target=target,
            observation_time=epoch.time,
            z_au=z_au,
            role=role,
            observer=request.observer,
            ephemeris=ephemeris,
            model=model,
            step_s=RATE_STEP_S,
        )
        # The near boundary is the interval's fastest point (rate ~ 1/z), so
        # motion padding must be sized there, not at the representative.
        near_rates = (
            rates
            if segment.is_point
            else motion_rates(
                target=target,
                observation_time=epoch.time,
                z_au=segment.z_near_au,
                role=role,
                observer=request.observer,
                ephemeris=ephemeris,
                model=model,
                step_s=RATE_STEP_S,
            )
        )

    direction = solution.direction
    validity = direction.validity
    if apparent_warnings and validity is Validity.VALID:
        validity = Validity.DEGRADED
    return LocusSample(
        calculation_id=calculation_id,
        epoch_id=epoch.epoch_id,
        target_id=target.target_id,
        role=role,
        sample_id=_sample_id(segment),
        observation_time_utc=str(epoch.time.utc.isot),
        observation_time_tdb_jd=float(direction.observation_epoch.jd),
        catalog_direction_epoch_tdb_jd=float(direction.catalog_direction_epoch.jd),
        relay_event_epoch_tdb_jd_approx=float(direction.relay_event_epoch_approx.jd),
        solar_lens_epoch_tdb_jd_approx=float(direction.solar_lens_epoch_approx.jd),
        target_event_epoch_tdb_jd_approx=float(direction.target_event_epoch_approx.jd),
        target_event_kind=direction.target_event_kind,
        target_light_time_days=direction.target_light_time_days,
        sun_relay_light_time_days=direction.sun_relay_light_time_days,
        observer_relay_light_time_days_approx=(
            direction.observer_relay_light_time_days_approx
        ),
        z_au=z_au,
        q_per_au=1.0 / z_au,
        icrs_ra_deg=solution.los_icrs_ra_deg,
        icrs_dec_deg=solution.los_icrs_dec_deg,
        observer_id=request.observer.observer_id,
        model_id=direction.model_id,
        model_version=direction.model_version,
        target_source_hash=target_source_hash,
        ephemeris_id=solution.ephemeris_id,
        target_provider_id=target_provider[0],
        target_provider_version=target_provider[1],
        target_provider_hash=target_provider[2],
        observer_provider_id=observer_provider[0],
        observer_provider_version=observer_provider[1],
        observer_provider_hash=observer_provider[2],
        validity=validity,
        uncertainty_method=uncertainty_method,
        warnings=(*direction.warnings, *apparent_warnings),
        interval_id=epoch.interval_id,
        interval_phase=epoch.interval_phase,
        interval_duration_s=epoch.interval_duration_s,
        cirs_ra_deg=cirs[0],
        cirs_dec_deg=cirs[1],
        altaz_alt_deg=altaz[0],
        altaz_az_deg=altaz[1],
        rate_ra_cosdec_arcsec_per_hr=(
            rates.rate_ra_cosdec_arcsec_per_hr if rates else None
        ),
        rate_dec_arcsec_per_hr=rates.rate_dec_arcsec_per_hr if rates else None,
        z_near_au=segment.z_near_au,
        z_far_au=segment.z_far_au,
        q_lo_per_au=segment.q_lo_per_au,
        q_hi_per_au=segment.q_hi_per_au,
        near_icrs_ra_deg=near_solution.los_icrs_ra_deg,
        near_icrs_dec_deg=near_solution.los_icrs_dec_deg,
        far_icrs_ra_deg=far_solution.los_icrs_ra_deg,
        far_icrs_dec_deg=far_solution.los_icrs_dec_deg,
        near_rate_ra_cosdec_arcsec_per_hr=(
            near_rates.rate_ra_cosdec_arcsec_per_hr if near_rates else None
        ),
        near_rate_dec_arcsec_per_hr=(
            near_rates.rate_dec_arcsec_per_hr if near_rates else None
        ),
    )


def _invalid_sample(
    *,
    request: GeometryRequest,
    target: Target,
    role: Role,
    epoch: Epoch,
    segment: RangeSegment,
    calculation_id: str,
    target_source_hash: str,
    ephemeris_id: str,
    model: GeometryModel,
    uncertainty_method: UncertaintyMethod,
    target_provider: tuple[str, str, str],
    observer_provider: tuple[str, str, str],
    reason: str,
) -> LocusSample:
    """An explicitly invalid status row: NaN coordinates, never fake values."""
    nan = float("nan")
    z_au = segment.z_rep_au
    return LocusSample(
        calculation_id=calculation_id,
        epoch_id=epoch.epoch_id,
        target_id=target.target_id,
        role=role,
        sample_id=_sample_id(segment),
        observation_time_utc=str(epoch.time.utc.isot),
        observation_time_tdb_jd=float(epoch.time.tdb.jd),
        catalog_direction_epoch_tdb_jd=nan,
        relay_event_epoch_tdb_jd_approx=nan,
        solar_lens_epoch_tdb_jd_approx=nan,
        target_event_epoch_tdb_jd_approx=nan,
        target_event_kind=_ROLE_EVENT_KIND[role],
        target_light_time_days=nan,
        sun_relay_light_time_days=z_au / C_AU_PER_DAY,
        observer_relay_light_time_days_approx=z_au / C_AU_PER_DAY,
        z_au=z_au,
        q_per_au=1.0 / z_au,
        icrs_ra_deg=nan,
        icrs_dec_deg=nan,
        observer_id=request.observer.observer_id,
        model_id=model.model_id,
        model_version=model.model_version,
        target_source_hash=target_source_hash,
        ephemeris_id=ephemeris_id,
        target_provider_id=target_provider[0],
        target_provider_version=target_provider[1],
        target_provider_hash=target_provider[2],
        observer_provider_id=observer_provider[0],
        observer_provider_version=observer_provider[1],
        observer_provider_hash=observer_provider[2],
        validity=Validity.INVALID,
        uncertainty_method=uncertainty_method,
        warnings=(reason,),
        interval_id=epoch.interval_id,
        interval_phase=epoch.interval_phase,
        interval_duration_s=epoch.interval_duration_s,
        z_near_au=segment.z_near_au,
        z_far_au=segment.z_far_au,
        q_lo_per_au=segment.q_lo_per_au,
        q_hi_per_au=segment.q_hi_per_au,
        near_icrs_ra_deg=nan,
        near_icrs_dec_deg=nan,
        far_icrs_ra_deg=nan,
        far_icrs_dec_deg=nan,
    )


def _build_corridor(
    *,
    request: GeometryRequest,
    calculation_id: str,
    target: Target,
    role: Role,
    epoch: Epoch,
    corridor_samples: tuple[LocusSample, ...],
    uncertainty_method: UncertaintyMethod,
) -> Corridor:
    corridor_warnings = tuple(
        sorted({code for sample in corridor_samples for code in sample.warnings})
    )
    return Corridor(
        corridor_id=stable_id(
            "cor",
            {
                "calculation_id": calculation_id,
                "target_id": target.target_id,
                "role": role,
                "epoch_id": epoch.epoch_id,
            },
        ),
        calculation_id=calculation_id,
        target_id=target.target_id,
        role=role,
        epoch_id=epoch.epoch_id,
        samples=corridor_samples,
        z_min_au=request.relay_range.z_min_au,
        z_max_au=request.relay_range.z_max_au,
        uncertainty_method=uncertainty_method,
        assumed_half_width_arcsec=request.assumed_half_width_arcsec,
        warnings=corridor_warnings,
    )
