"""Curated target registry: loading, strict validation, and identity.

The registry is a reviewable YAML file (schema v1), not a service-backed
catalog. Loading is strict: finite values, explicit frame and reference
epoch/scale, real provenance, and a declared endpoint kind are required, and
unknown keys are rejected so typos cannot silently drop a field.

Missing radial velocity is a validation error by default; callers may instead
ask for a flagged target (``missing_radial_velocity="flag"``), which records
``radial_velocity_km_s=None`` plus the ``missing_radial_velocity`` flag — it
is never silently replaced with zero.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .config import _build, _check_keys, _fail_factory, _mapping, _number, load_yaml
from .models import AstrometricState, EndpointKind, Target
from .provenance import stable_hash

__all__ = [
    "TARGETS_SCHEMA_VERSION",
    "TargetRegistry",
    "load_target_registry",
]

TARGETS_SCHEMA_VERSION = 1

#: Flag recorded on a target loaded with a missing radial velocity.
MISSING_RV_FLAG = "missing_radial_velocity"

_TARGET_KEYS = {"display_name", "endpoint_kind", "priority", "tags", "flags", "notes", "astrometry"}
_ASTROMETRY_KEYS = {
    "frame",
    "ra_deg",
    "dec_deg",
    "parallax_mas",
    "distance_pc",
    "pm_ra_cosdec_mas_per_yr",
    "pm_dec_mas_per_yr",
    "radial_velocity_km_s",
    "reference_epoch_jyear",
    "reference_epoch_scale",
    "source",
}


@dataclass(frozen=True)
class TargetRegistry:
    """Immutable mapping of target IDs to validated targets.

    ``source_hash`` is a SHA-256 over the normalized registry content
    (sorted-key JSON of :meth:`to_normalized_dict`), so it is stable across
    formatting, key order, and comment changes in the source file.
    """

    targets: tuple[Target, ...]
    source_hash: str

    def __getitem__(self, target_id: str) -> Target:
        for target in self.targets:
            if target.target_id == target_id:
                return target
        known = sorted(target.target_id for target in self.targets)
        raise KeyError(f"unknown target ID {target_id!r}; registry contains {known}")

    def __contains__(self, target_id: object) -> bool:
        return any(target.target_id == target_id for target in self.targets)

    def __iter__(self) -> Iterator[Target]:
        return iter(self.targets)

    def __len__(self) -> int:
        return len(self.targets)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(target.target_id for target in self.targets)

    def to_normalized_dict(self) -> dict[str, Any]:
        """Return a canonical plain-dict form that reloads to an equal registry.

        ``None`` values are omitted; this dict (dumped as YAML) is itself a
        valid registry file.
        """
        targets: dict[str, Any] = {}
        for target in sorted(self.targets, key=lambda t: t.target_id):
            astrometry = {
                "frame": target.astrometry.frame,
                "ra_deg": target.astrometry.ra_deg,
                "dec_deg": target.astrometry.dec_deg,
                "pm_ra_cosdec_mas_per_yr": target.astrometry.pm_ra_cosdec_mas_per_yr,
                "pm_dec_mas_per_yr": target.astrometry.pm_dec_mas_per_yr,
                "reference_epoch_jyear": target.astrometry.reference_epoch_jyear,
                "reference_epoch_scale": target.astrometry.reference_epoch_scale,
                "source": target.astrometry.source,
            }
            if target.astrometry.parallax_mas is not None:
                astrometry["parallax_mas"] = target.astrometry.parallax_mas
            if target.astrometry.distance_pc is not None:
                astrometry["distance_pc"] = target.astrometry.distance_pc
            if target.astrometry.radial_velocity_km_s is not None:
                astrometry["radial_velocity_km_s"] = target.astrometry.radial_velocity_km_s
            targets[target.target_id] = {
                "display_name": target.display_name,
                "endpoint_kind": target.endpoint_kind.value,
                "priority": target.priority,
                "tags": list(target.tags),
                "flags": list(target.flags),
                "notes": target.notes,
                "astrometry": astrometry,
            }
        return {"schema_version": TARGETS_SCHEMA_VERSION, "targets": targets}

    @classmethod
    def from_targets(cls, targets: tuple[Target, ...]) -> TargetRegistry:
        registry = cls(targets=targets, source_hash="")
        return cls(
            targets=targets,
            source_hash=stable_hash(registry.to_normalized_dict()),
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        missing_radial_velocity: Literal["error", "flag"] = "error",
    ) -> TargetRegistry:
        return load_target_registry(path, missing_radial_velocity=missing_radial_velocity)


def load_target_registry(
    path: str | Path,
    *,
    missing_radial_velocity: Literal["error", "flag"] = "error",
) -> TargetRegistry:
    """Load and strictly validate a versioned target registry YAML file."""
    path = Path(path)
    fail = _fail_factory(path)
    data = load_yaml(path)
    if data.get("schema_version") != TARGETS_SCHEMA_VERSION:
        fail("schema_version", f"must be {TARGETS_SCHEMA_VERSION}")
    _check_keys(data, {"schema_version", "targets"}, "registry", fail)
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, dict) or not raw_targets:
        fail("targets", "must be a non-empty mapping of target IDs")

    targets: list[Target] = []
    for target_id, raw in raw_targets.items():
        if not isinstance(target_id, str) or not target_id:
            fail("targets", f"target keys must be non-empty strings, got {target_id!r}")
        ctx = f"targets.{target_id}"
        block = _mapping(raw, ctx, fail)
        _check_keys(block, _TARGET_KEYS, ctx, fail)

        astro_ctx = f"{ctx}.astrometry"
        astro = _mapping(block.get("astrometry"), astro_ctx, fail)
        _check_keys(astro, _ASTROMETRY_KEYS, astro_ctx, fail)

        frame = astro.get("frame")
        if not isinstance(frame, str):
            fail(f"{astro_ctx}.frame", "is required (v1 supports only 'icrs')")
        for required in ("reference_epoch_scale", "source"):
            if not isinstance(astro.get(required), str) or not str(astro[required]).strip():
                fail(f"{astro_ctx}.{required}", "is required and must be a non-empty string")

        parallax = (
            _number(astro, "parallax_mas", astro_ctx, fail)
            if "parallax_mas" in astro
            else None
        )
        distance = (
            _number(astro, "distance_pc", astro_ctx, fail) if "distance_pc" in astro else None
        )

        flags = _parse_str_tuple(block.get("flags", []), f"{ctx}.flags", fail)
        radial_velocity: float | None
        if "radial_velocity_km_s" in astro:
            radial_velocity = _number(astro, "radial_velocity_km_s", astro_ctx, fail)
        elif missing_radial_velocity == "flag":
            radial_velocity = None
            if MISSING_RV_FLAG not in flags:
                flags = (*flags, MISSING_RV_FLAG)
        else:
            fail(
                f"{astro_ctx}.radial_velocity_km_s",
                "is required; reload with missing_radial_velocity='flag' "
                "(CLI: --allow-missing-rv) to accept a flagged target instead",
            )

        state: AstrometricState = _build(
            astro_ctx,
            fail,
            AstrometricState,
            ra_deg=_number(astro, "ra_deg", astro_ctx, fail),
            dec_deg=_number(astro, "dec_deg", astro_ctx, fail),
            pm_ra_cosdec_mas_per_yr=_number(astro, "pm_ra_cosdec_mas_per_yr", astro_ctx, fail),
            pm_dec_mas_per_yr=_number(astro, "pm_dec_mas_per_yr", astro_ctx, fail),
            reference_epoch_jyear=_number(astro, "reference_epoch_jyear", astro_ctx, fail),
            reference_epoch_scale=str(astro["reference_epoch_scale"]).strip().lower(),
            source=str(astro["source"]).strip(),
            parallax_mas=parallax,
            distance_pc=distance,
            radial_velocity_km_s=radial_velocity,
            frame=frame.strip().lower(),
        )

        endpoint_raw = block.get("endpoint_kind")
        if not isinstance(endpoint_raw, str):
            fail(
                f"{ctx}.endpoint_kind",
                f"is required; choose from {[k.value for k in EndpointKind]}",
            )
        try:
            endpoint_kind = EndpointKind(endpoint_raw.strip().lower())
        except ValueError:
            fail(
                f"{ctx}.endpoint_kind",
                f"unknown kind {endpoint_raw!r}; choose from {[k.value for k in EndpointKind]}",
            )

        priority = _number(block, "priority", ctx, fail) if "priority" in block else 1.0
        targets.append(
            _build(
                ctx,
                fail,
                Target,
                target_id=target_id,
                display_name=str(block.get("display_name", target_id)),
                endpoint_kind=endpoint_kind,
                astrometry=state,
                priority=priority,
                tags=_parse_str_tuple(block.get("tags", []), f"{ctx}.tags", fail),
                flags=flags,
                notes=str(block.get("notes", "")),
            )
        )

    return TargetRegistry.from_targets(tuple(targets))


def _parse_str_tuple(raw: Any, ctx: str, fail: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        fail(ctx, "must be a list of strings")
    items = tuple(str(item).strip() for item in raw)
    if len(set(items)) != len(items):
        fail(ctx, "must not contain duplicates")
    return items
