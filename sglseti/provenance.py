"""Canonical serialization, stable hashing, and manifest building.

Stable IDs are science-input identities: equivalent normalized inputs must
hash equally across runs, machines, and working directories, and every
scientific change must change the hash. The rules (implementation of plan
§4.4), versioned as ``CANONICAL_SCHEMA_VERSION``:

- mapping keys are strings and are sorted;
- list/tuple order is preserved (stable ordering is the caller's contract);
- floats must be finite; ``-0.0`` normalizes to ``0.0``; integral floats
  (``550.0``) normalize to ints so YAML int/float ambiguity cannot split
  identities;
- enums serialize as their values;
- dataclasses serialize with their class name, so two record types with the
  same field values stay distinct;
- astropy ``Time`` normalizes to a TDB ISO string at nanosecond precision
  (UTC/TDB expressions of one instant hash equally);
- astropy ``Quantity`` normalizes to SI-decomposed unit/value pairs
  (``1 au`` and ``149597870700 m`` hash equally);
- filesystem paths are rejected: identities use resource *content* hashes
  (:func:`file_sha256`), never locations.

The hash payload embeds the schema version, so any change to these rules
changes every hash loudly rather than silently.

Astropy types are handled by duck-typing — this module imports neither
astropy nor any other application module, keeping ``sglseti samples`` and
``validate`` light.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "build_manifest",
    "canonical_json",
    "canonicalize",
    "file_sha256",
    "request_id",
    "stable_hash",
    "stable_id",
]

CANONICAL_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1


def canonicalize(value: Any) -> Any:
    """Return a JSON-safe canonical structure for ``value``.

    Raises ``TypeError`` for unsupported types and ``ValueError`` for
    non-finite floats; both are identity bugs, never silently absorbed.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float {value!r} cannot enter a stable identity")
        if value == 0.0:
            return 0
        if value.is_integer() and abs(value) < 2**53:
            return int(value)
        return value
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, (Path, os.PathLike)):
        raise TypeError(
            "filesystem paths must not enter a stable identity; hash the file "
            "content with file_sha256() instead"
        )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": type(value).__name__,
            "fields": {
                field.name: canonicalize(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if _is_astropy_time(value):
        return {"__time__": _normalize_time(value)}
    if _is_astropy_quantity(value):
        return {"__quantity__": _normalize_quantity(value)}
    if _is_numpy_scalar(value):
        return canonicalize(value.item())
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise TypeError(f"mapping keys must be strings, got {key!r}")
            out[key] = canonicalize(value[key])
        return out
    if isinstance(value, (bytes, bytearray)):
        raise TypeError("raw bytes have no canonical form; hash them explicitly")
    if isinstance(value, Sequence):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError("sets are unordered; pass a sorted sequence instead")
    raise TypeError(f"type {type(value).__name__} has no canonical serialization")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def stable_hash(value: Any) -> str:
    """SHA-256 over the canonical form, as ``sha256:<hex>``.

    The canonical schema version is part of the hashed payload.
    """
    envelope = {
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "payload": canonicalize(value),
    }
    blob = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


def stable_id(prefix: str, value: Any) -> str:
    """Short deterministic identifier: ``<prefix>-<first 12 hash hex chars>``."""
    digest = stable_hash(value).removeprefix("sha256:")
    return f"{prefix}-{digest[:12]}"


def request_id(request: Any) -> str:
    """Stable identity of a calculation request (``req-`` prefix).

    Path-independent: epochs are held resolved (never as file references),
    and an ephemeris ``path`` is stripped from the identity — a file-backed
    ephemeris contributes through its content checksum, not its location.
    """
    canonical = canonicalize(request)
    _strip_ephemeris_path(canonical)
    return stable_id("req", canonical)


def _strip_ephemeris_path(canonical: Any) -> None:
    """Remove a canonicalized EphemerisSpec's ``path`` in place, if present."""
    if isinstance(canonical, list):
        for item in canonical:
            _strip_ephemeris_path(item)
        return
    if not isinstance(canonical, dict):
        return
    fields = canonical.get("fields")
    if canonical.get("__dataclass__") == "EphemerisSpec" and isinstance(fields, dict):
        fields.pop("path", None)
        return
    for value in canonical.values():
        _strip_ephemeris_path(value)


def file_sha256(path: str | Path) -> str:
    """Content hash of a file-backed resource, as ``sha256:<hex>``."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_manifest(
    *,
    science_inputs: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a provenance manifest separating identity from circumstance.

    ``science_inputs`` determine ``science_input_hash`` (and therefore every
    stable ID derived from them). ``run_metadata`` — generation timestamp,
    output locations (as strings), host details, library versions — is
    recorded verbatim next to the science block and never influences the
    hash.
    """
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "science_inputs": canonicalize(science_inputs),
        "science_input_hash": stable_hash(science_inputs),
        "run": dict(run_metadata),
    }


# ---------------------------------------------------------------------------
# Duck-typed astropy/numpy handling (no astropy import at module level)
# ---------------------------------------------------------------------------


def _is_astropy_time(value: Any) -> bool:
    return hasattr(value, "isot") and hasattr(value, "scale") and hasattr(value, "tdb")


def _is_astropy_quantity(value: Any) -> bool:
    return hasattr(value, "unit") and hasattr(value, "to_value") and hasattr(value, "si")


def _is_numpy_scalar(value: Any) -> bool:
    return hasattr(value, "item") and getattr(value, "shape", None) == ()


def _normalize_time(value: Any) -> Any:
    # One instant, one representation: TDB ISO at nanosecond precision.
    tdb = value.tdb.replicate()
    tdb.precision = 9
    isot = tdb.isot
    if getattr(isot, "shape", ()) != ():
        return [str(item) for item in isot]
    return str(isot)


def _normalize_quantity(value: Any) -> dict[str, Any]:
    decomposed = value.si
    raw = decomposed.value
    if getattr(raw, "shape", ()) not in ((), None):
        normalized: Any = [canonicalize(float(item)) for item in raw.flat]
    else:
        normalized = canonicalize(float(raw))
    return {"unit": str(decomposed.unit), "value": normalized}
