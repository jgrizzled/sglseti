"""Domain exceptions shared across the package.

Every user-facing error raised by sglseti derives from :class:`SglsetiError`
so the CLI can report it concisely and exit with status 2, while genuine
programming errors keep their tracebacks.
"""

from __future__ import annotations

__all__ = ["ConfigError", "SglsetiError"]


class SglsetiError(Exception):
    """Base class for errors caused by invalid user input or resources."""


class ConfigError(SglsetiError):
    """Raised when a configuration or input file is invalid."""
