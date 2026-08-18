"""Domain exceptions shared across the package.

Every user-facing error raised by sglseti derives from :class:`SglsetiError`
so the CLI can report it concisely and exit with status 2, while genuine
programming errors keep their tracebacks.
"""

from __future__ import annotations

__all__ = [
    "ConfigError",
    "EphemerisCoverageError",
    "EphemerisError",
    "GenerationError",
    "PlanningError",
    "SglsetiError",
]


class SglsetiError(Exception):
    """Base class for errors caused by invalid user input or resources."""


class ConfigError(SglsetiError):
    """Raised when a configuration or input file is invalid."""


class EphemerisError(SglsetiError):
    """Raised when an ephemeris resource is missing, unreadable, or unusable."""


class EphemerisCoverageError(EphemerisError):
    """Raised when a requested epoch lies outside the ephemeris coverage."""


class GenerationError(SglsetiError):
    """Raised when a batch calculation cannot proceed or fails strict mode."""


class PlanningError(SglsetiError):
    """Raised when commensal planning inputs are unusable."""
