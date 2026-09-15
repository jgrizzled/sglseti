"""SGLSETI: reproducible sky-target generation for SGL technosignature searches.

SGLSETI turns a curated stellar-system hypothesis, an observer, and past or
future epochs into reproducible, telescope-usable solar-gravitational-lens
target regions.

The package ends at the generation and export of target products. Archive
discovery, observation ingest, historical-coverage accounting, and candidate
management belong to other projects, and no module in this package may depend
on an observation ledger or mutable service database.

Importing :mod:`sglseti` must stay side-effect free: no file reads, no network
access, and no heavy scientific imports at package-import time. Public names
below are therefore re-exported lazily (PEP 562); accessing one imports its
defining module on first use.
"""

# ruff: noqa: F401 -- TYPE_CHECKING imports below back the lazy _EXPORTS table.
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "1.1.0"

# name -> defining submodule, resolved lazily on attribute access.
_EXPORTS = {
    "SglsetiError": "sglseti.errors",
    "ConfigError": "sglseti.errors",
    "EphemerisError": "sglseti.errors",
    "EphemerisCoverageError": "sglseti.errors",
    "AstropyEphemeris": "sglseti.ephemeris",
    "IersResource": "sglseti.ephemeris",
    "KNOWN_KERNELS": "sglseti.resources",
    "fetch_kernel": "sglseti.resources",
    "fetch_iers": "sglseti.resources",
    "Tusay2022Eq57V1": "sglseti.geometry",
    "TargetState": "sglseti.providers",
    "TargetStateProvider": "sglseti.providers",
    "LinearAstrometryV1": "sglseti.providers",
    "AccelerationAstrometryV1": "sglseti.providers",
    "TwoBodyOrbitV1": "sglseti.providers",
    "SampledStateV1": "sglseti.providers",
    "ObserverState": "sglseti.providers",
    "ObserverStateProvider": "sglseti.providers",
    "EarthCenterObserverV1": "sglseti.providers",
    "TerrestrialSiteObserverV1": "sglseti.providers",
    "resolve_target_state_provider": "sglseti.providers",
    "resolve_observer_state_provider": "sglseti.providers",
    "compute_relay_solution": "sglseti.geometry",
    "motion_rates": "sglseti.geometry",
    "solar_focal_min_au": "sglseti.geometry",
    "generate_loci": "sglseti.generate",
    "materialize_epochs": "sglseti.generate",
    "plan_calculation": "sglseti.generate",
    "iter_locus_chunks": "sglseti.generate",
    "CalculationPlan": "sglseti.generate",
    "LocusChunk": "sglseti.generate",
    "clear_provider_cache": "sglseti.providers",
    "provider_cache_stats": "sglseti.providers",
    "SolarSystemBodyObserverV1": "sglseti.providers",
    "TabularSpacecraftObserverV1": "sglseti.providers",
    "SpiceSpacecraftObserverV1": "sglseti.providers",
    "ProgrammaticObserverV1": "sglseti.providers",
    "register_programmatic_observer": "sglseti.providers",
    "unregister_programmatic_observer": "sglseti.providers",
    "evaluate_locus": "sglseti.locus",
    "adaptive_locus": "sglseti.locus",
    "swept_locus": "sglseti.locus",
    "covered_z_intervals": "sglseti.locus",
    "interval_states": "sglseti.locus",
    "GenerationError": "sglseti.errors",
    "PlanningError": "sglseti.errors",
    "plan_commensal": "sglseti.planning",
    "AXIS_MODEL_ID": "sglseti.crossings",
    "AXIS_MODEL_VERSION": "sglseti.crossings",
    "find_crossings": "sglseti.crossings",
    "impact_parameter": "sglseti.crossings",
    "minimize_impact_parameter": "sglseti.crossings",
    "TargetUncertainty": "sglseti.uncertainty",
    "LocusUncertainty": "sglseti.uncertainty",
    "CrossingUncertainty": "sglseti.uncertainty",
    "target_uncertainty": "sglseti.uncertainty",
    "draw_target_samples": "sglseti.uncertainty",
    "propagate_locus_uncertainty": "sglseti.uncertainty",
    "crossing_uncertainty": "sglseti.uncertainty",
    "write_products": "sglseti.export",
    "write_samples_stream": "sglseti.export",
    "result_manifest": "sglseti.export",
    "RESULT_SCHEMA_VERSION": "sglseti.export",
    "write_crossings_products": "sglseti.export",
    "crossings_manifest": "sglseti.export",
    "CROSSINGS_RESULT_SCHEMA_VERSION": "sglseti.export",
    "VisibilityWindow": "sglseti.observability",
    "find_windows": "sglseti.observability",
    "visibility_sample": "sglseti.observability",
    "Role": "sglseti.models",
    "LinkDirection": "sglseti.models",
    "BeamSide": "sglseti.models",
    "EndpointKind": "sglseti.models",
    "Validity": "sglseti.models",
    "UncertaintyMethod": "sglseti.models",
    "CorrectionType": "sglseti.models",
    "TargetEventKind": "sglseti.models",
    "ObserverKind": "sglseti.models",
    "SamplingKind": "sglseti.models",
    "EphemerisAdapter": "sglseti.models",
    "CoordinateProduct": "sglseti.models",
    "OutputFormat": "sglseti.models",
    "DirectionSolution": "sglseti.models",
    "ObservationInterval": "sglseti.models",
    "LocusPoint": "sglseti.models",
    "AdaptiveLocus": "sglseti.models",
    "SweptLocus": "sglseti.models",
    "ZInterval": "sglseti.models",
    "IntervalState": "sglseti.models",
    "SUPPORTED_MODEL_IDS": "sglseti.models",
    "SUPPORTED_TARGET_STATE_PROVIDERS": "sglseti.models",
    "AccelerationTerms": "sglseti.models",
    "CatalogIdentifier": "sglseti.models",
    "CovarianceKind": "sglseti.models",
    "CovarianceSpec": "sglseti.models",
    "OrbitComponent": "sglseti.models",
    "OrbitSolution": "sglseti.models",
    "ParameterProvenance": "sglseti.models",
    "SampledStateSpec": "sglseti.models",
    "AstrometricState": "sglseti.models",
    "Target": "sglseti.models",
    "Observer": "sglseti.models",
    "EphemerisSpec": "sglseti.models",
    "IersSpec": "sglseti.models",
    "RelayRange": "sglseti.models",
    "SamplingSpec": "sglseti.models",
    "Epoch": "sglseti.models",
    "TimeSingle": "sglseti.models",
    "TimeList": "sglseti.models",
    "TimeGrid": "sglseti.models",
    "TimeInterval": "sglseti.models",
    "ObservabilityConstraints": "sglseti.models",
    "FieldOfView": "sglseti.models",
    "GeometryRequest": "sglseti.models",
    "CrossingsRequest": "sglseti.models",
    "LocusSample": "sglseti.models",
    "Corridor": "sglseti.models",
    "VisibilitySample": "sglseti.models",
    "Pointing": "sglseti.models",
    "CalculationResult": "sglseti.models",
    "RangeSegment": "sglseti.models",
    "ImpactSample": "sglseti.models",
    "BeamWindow": "sglseti.models",
    "CrossingEvent": "sglseti.models",
    "CrossingsResult": "sglseti.models",
    "TargetRegistry": "sglseti.targets",
    "load_target_registry": "sglseti.targets",
    "load_request": "sglseti.config",
    "load_crossings_request": "sglseti.config",
    "load_epoch_table": "sglseti.config",
    "generate_segments": "sglseti.sampling",
    "segments_for_request": "sglseti.sampling",
    "build_manifest": "sglseti.provenance",
    "canonical_json": "sglseti.provenance",
    "file_sha256": "sglseti.provenance",
    "request_id": "sglseti.provenance",
    "stable_hash": "sglseti.provenance",
    "stable_id": "sglseti.provenance",
}

__all__ = ["__version__", *sorted(_EXPORTS)]

if TYPE_CHECKING:
    from .config import load_crossings_request, load_epoch_table, load_request
    from .crossings import (
        AXIS_MODEL_ID,
        AXIS_MODEL_VERSION,
        find_crossings,
        impact_parameter,
        minimize_impact_parameter,
    )
    from .ephemeris import AstropyEphemeris, IersResource
    from .errors import (
        ConfigError,
        EphemerisCoverageError,
        EphemerisError,
        GenerationError,
        PlanningError,
        SglsetiError,
    )
    from .export import (
        CROSSINGS_RESULT_SCHEMA_VERSION,
        RESULT_SCHEMA_VERSION,
        crossings_manifest,
        result_manifest,
        write_crossings_products,
        write_products,
        write_samples_stream,
    )
    from .generate import (
        CalculationPlan,
        LocusChunk,
        generate_loci,
        iter_locus_chunks,
        materialize_epochs,
        plan_calculation,
    )
    from .geometry import (
        Tusay2022Eq57V1,
        compute_relay_solution,
        motion_rates,
        solar_focal_min_au,
    )
    from .locus import (
        adaptive_locus,
        covered_z_intervals,
        evaluate_locus,
        interval_states,
        swept_locus,
    )
    from .models import (
        SUPPORTED_MODEL_IDS,
        SUPPORTED_TARGET_STATE_PROVIDERS,
        AccelerationTerms,
        AdaptiveLocus,
        AstrometricState,
        BeamSide,
        BeamWindow,
        CalculationResult,
        CatalogIdentifier,
        CoordinateProduct,
        CorrectionType,
        Corridor,
        CovarianceKind,
        CovarianceSpec,
        CrossingEvent,
        CrossingsRequest,
        CrossingsResult,
        DirectionSolution,
        EndpointKind,
        EphemerisAdapter,
        EphemerisSpec,
        Epoch,
        FieldOfView,
        GeometryRequest,
        IersSpec,
        ImpactSample,
        IntervalState,
        LinkDirection,
        LocusPoint,
        LocusSample,
        ObservabilityConstraints,
        ObservationInterval,
        Observer,
        ObserverKind,
        OrbitComponent,
        OrbitSolution,
        OutputFormat,
        ParameterProvenance,
        Pointing,
        RangeSegment,
        RelayRange,
        Role,
        SampledStateSpec,
        SamplingKind,
        SamplingSpec,
        SweptLocus,
        Target,
        TargetEventKind,
        TimeGrid,
        TimeInterval,
        TimeList,
        TimeSingle,
        UncertaintyMethod,
        Validity,
        VisibilitySample,
        ZInterval,
    )
    from .observability import VisibilityWindow, find_windows, visibility_sample
    from .planning import plan_commensal
    from .provenance import (
        build_manifest,
        canonical_json,
        file_sha256,
        request_id,
        stable_hash,
        stable_id,
    )
    from .providers import (
        AccelerationAstrometryV1,
        EarthCenterObserverV1,
        LinearAstrometryV1,
        ObserverState,
        ObserverStateProvider,
        ProgrammaticObserverV1,
        SampledStateV1,
        SolarSystemBodyObserverV1,
        SpiceSpacecraftObserverV1,
        TabularSpacecraftObserverV1,
        TargetState,
        TargetStateProvider,
        TerrestrialSiteObserverV1,
        TwoBodyOrbitV1,
        clear_provider_cache,
        provider_cache_stats,
        register_programmatic_observer,
        resolve_observer_state_provider,
        resolve_target_state_provider,
        unregister_programmatic_observer,
    )
    from .resources import KNOWN_KERNELS, fetch_iers, fetch_kernel
    from .sampling import generate_segments, segments_for_request
    from .targets import TargetRegistry, load_target_registry
    from .uncertainty import (
        CrossingUncertainty,
        LocusUncertainty,
        TargetUncertainty,
        crossing_uncertainty,
        draw_target_samples,
        propagate_locus_uncertainty,
        target_uncertainty,
    )


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
