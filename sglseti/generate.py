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
"""

from __future__ import annotations

import math

from .ephemeris import AstropyEphemeris, Ephemeris
from .errors import EphemerisCoverageError, GenerationError
from .geometry import (
    C_AU_PER_DAY,
    GeometryModel,
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
    TimeList,
    TimeSingle,
    TimeSpec,
    UncertaintyMethod,
    Validity,
)
from .provenance import canonicalize, stable_hash, stable_id
from .sampling import generate_segments
from .targets import TargetRegistry

__all__ = [
    "MAX_MATERIALIZED_EPOCHS",
    "RATE_STEP_S",
    "generate_loci",
    "materialize_epochs",
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
    in ascending time order; list and single modes keep caller IDs.
    """
    if isinstance(time_spec, TimeSingle):
        return (time_spec.epoch,)
    if isinstance(time_spec, TimeList):
        return time_spec.epochs
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
    caller's responsibility to record.
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
    targets = [registry[tid] for tid in request.target_ids]
    target_hashes = {target.target_id: stable_hash(target) for target in targets}
    calculation_id = _calculation_id(request, model, ephemeris, target_hashes)

    uncertainty_method = (
        UncertaintyMethod.ASSUMED
        if request.assumed_half_width_arcsec is not None
        else UncertaintyMethod.NOT_PROPAGATED
    )
    want_cirs = CoordinateProduct.CIRS in request.coordinate_products
    want_altaz = CoordinateProduct.ALTAZ in request.coordinate_products

    samples: list[LocusSample] = []
    corridors: list[Corridor] = []
    invalid_count = 0
    degraded_count = 0

    for target in targets:
        for role in request.roles:
            segments = generate_segments(
                target_id=target.target_id,
                role=role,
                relay_range=request.relay_range,
                sampling=request.sampling,
            )
            for epoch in epochs:
                corridor_samples: list[LocusSample] = []
                for segment in segments:
                    sample = _compute_sample(
                        request=request,
                        target=target,
                        role=role,
                        epoch=epoch,
                        segment=segment,
                        model=model,
                        ephemeris=ephemeris,
                        calculation_id=calculation_id,
                        target_source_hash=target_hashes[target.target_id],
                        uncertainty_method=uncertainty_method,
                        want_cirs=want_cirs,
                        want_altaz=want_altaz,
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
                corridors.append(
                    _build_corridor(
                        request=request,
                        calculation_id=calculation_id,
                        target=target,
                        role=role,
                        epoch=epoch,
                        corridor_samples=tuple(corridor_samples),
                        uncertainty_method=uncertainty_method,
                    )
                )
                samples.extend(corridor_samples)

    warnings: list[str] = []
    if uncertainty_method is UncertaintyMethod.NOT_PROPAGATED:
        warnings.append(WARN_UNCERTAINTY_NOT_PROPAGATED)
    if invalid_count:
        warnings.append(f"invalid_sample_count:{invalid_count}")
    if degraded_count:
        warnings.append(f"degraded_sample_count:{degraded_count}")

    return CalculationResult(
        calculation_id=calculation_id,
        request=request,
        samples=tuple(samples),
        corridors=tuple(corridors),
        warnings=tuple(warnings),
    )


def _calculation_id(
    request: GeometryRequest,
    model: GeometryModel,
    ephemeris: Ephemeris,
    target_hashes: dict[str, str],
) -> str:
    canonical_request = canonicalize(request)
    # A file-backed ephemeris contributes its content identity, never its
    # location: replace the spec (which may carry a path) wholesale.
    canonical_request["fields"]["ephemeris"] = ephemeris.ephemeris_id
    return stable_id(
        "calc",
        {
            "request": canonical_request,
            "model": {"id": model.model_id, "version": model.model_version},
            "target_source_hashes": dict(sorted(target_hashes.items())),
            "ephemeris_id": ephemeris.ephemeris_id,
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
) -> LocusSample:
    z_au = segment.z_rep_au
    try:
        solution = compute_relay_solution(
            target=target,
            observation_time=epoch.time,
            z_au=z_au,
            role=role,
            observer=request.observer,
            ephemeris=ephemeris,
            model=model,
        )
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
            reason=f"{WARN_EPHEMERIS_COVERAGE}: {exc}",
        )

    cirs = cirs_apparent(solution) if want_cirs else (None, None)
    altaz = altaz_apparent(solution) if want_altaz else (None, None)
    rates = (
        motion_rates(
            target=target,
            observation_time=epoch.time,
            z_au=z_au,
            role=role,
            observer=request.observer,
            ephemeris=ephemeris,
            model=model,
            step_s=RATE_STEP_S,
        )
        if request.include_rates
        else None
    )

    direction = solution.direction
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
        validity=direction.validity,
        uncertainty_method=uncertainty_method,
        warnings=direction.warnings,
        cirs_ra_deg=cirs[0],
        cirs_dec_deg=cirs[1],
        altaz_alt_deg=altaz[0],
        altaz_az_deg=altaz[1],
        rate_ra_cosdec_arcsec_per_hr=(
            rates.rate_ra_cosdec_arcsec_per_hr if rates else None
        ),
        rate_dec_arcsec_per_hr=rates.rate_dec_arcsec_per_hr if rates else None,
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
        validity=Validity.INVALID,
        uncertainty_method=uncertainty_method,
        warnings=(reason,),
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
