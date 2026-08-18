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

__version__ = "0.1.0.dev0"

# name -> defining submodule, resolved lazily on attribute access.
_EXPORTS = {
    "SglsetiError": "sglseti.errors",
    "ConfigError": "sglseti.errors",
    "Role": "sglseti.models",
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
    "SUPPORTED_MODEL_IDS": "sglseti.models",
    "AstrometricState": "sglseti.models",
    "Target": "sglseti.models",
    "Observer": "sglseti.models",
    "EphemerisSpec": "sglseti.models",
    "RelayRange": "sglseti.models",
    "SamplingSpec": "sglseti.models",
    "Epoch": "sglseti.models",
    "TimeSingle": "sglseti.models",
    "TimeList": "sglseti.models",
    "TimeGrid": "sglseti.models",
    "ObservabilityConstraints": "sglseti.models",
    "FieldOfView": "sglseti.models",
    "GeometryRequest": "sglseti.models",
    "LocusSample": "sglseti.models",
    "Corridor": "sglseti.models",
    "VisibilitySample": "sglseti.models",
    "Pointing": "sglseti.models",
    "CalculationResult": "sglseti.models",
    "TargetRegistry": "sglseti.targets",
    "load_target_registry": "sglseti.targets",
    "load_request": "sglseti.config",
    "load_epoch_table": "sglseti.config",
}

__all__ = ["__version__", *sorted(_EXPORTS)]

if TYPE_CHECKING:
    from .config import load_epoch_table, load_request
    from .errors import ConfigError, SglsetiError
    from .models import (
        SUPPORTED_MODEL_IDS,
        AstrometricState,
        CalculationResult,
        CoordinateProduct,
        CorrectionType,
        Corridor,
        EndpointKind,
        EphemerisAdapter,
        EphemerisSpec,
        Epoch,
        FieldOfView,
        GeometryRequest,
        LocusSample,
        ObservabilityConstraints,
        Observer,
        ObserverKind,
        OutputFormat,
        Pointing,
        RelayRange,
        Role,
        SamplingKind,
        SamplingSpec,
        Target,
        TargetEventKind,
        TimeGrid,
        TimeList,
        TimeSingle,
        UncertaintyMethod,
        Validity,
        VisibilitySample,
    )
    from .targets import TargetRegistry, load_target_registry


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
