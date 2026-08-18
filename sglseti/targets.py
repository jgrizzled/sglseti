"""Curated target registry: loading, strict validation, and identity.

The registry is a reviewable YAML file (single schema, version 2), not a
service-backed catalog. Loading is strict: finite values, explicit frame
and reference epoch/scale, real provenance, and a declared endpoint kind
are required, and unknown keys are rejected so typos cannot silently drop
a field.

Each target's ``state`` block selects its target-state provider family
(``linear_astrometry_v1``, ``acceleration_astrometry_v1``,
``two_body_orbit_v1``, ``sampled_state_v1``) and carries the adopted
solution: astrometry, immutable catalog identifiers, per-value provenance,
uncertainties with units, full covariance/correlation matrices with a
declared parameter ordering, and quality/model-selection metadata. For
``two_body_orbit_v1`` the ``state.astrometry`` block describes the system
BARYCENTER; for ``sampled_state_v1`` it is the approximate reference
solution beside the checksummed table. See ``docs/registry.md``.

Identity: ``source_hash`` covers the normalized registry content
(sorted-key JSON of :meth:`TargetRegistry.to_normalized_dict`), stable
across formatting, key order, and comment changes in the source file.

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

from .config import (
    _build,
    _check_keys,
    _Fail,
    _fail_factory,
    _mapping,
    _number,
    _string,
    load_yaml,
)
from .models import (
    SUPPORTED_TARGET_STATE_PROVIDERS,
    AccelerationTerms,
    AstrometricState,
    CatalogIdentifier,
    CovarianceKind,
    CovarianceSpec,
    EndpointKind,
    OrbitComponent,
    OrbitSolution,
    ParameterProvenance,
    SampledStateSpec,
    Target,
)
from .provenance import stable_hash

__all__ = [
    "TARGETS_SCHEMA_VERSION",
    "TargetRegistry",
    "load_target_registry",
]

#: The single supported registry schema version.
TARGETS_SCHEMA_VERSION = 2

#: Flag recorded on a target loaded with a missing radial velocity.
MISSING_RV_FLAG = "missing_radial_velocity"

_TARGET_KEYS = {
    "display_name",
    "endpoint_kind",
    "priority",
    "tags",
    "flags",
    "notes",
    "identifiers",
    "quality",
    "model_rationale",
    "state",
}
_STATE_KEYS = {
    "provider",
    "astrometry",
    "provenance",
    "covariance",
    "acceleration",
    "orbit",
    "sampled_state",
}
_SAMPLED_STATE_KEYS = {"path", "checksum_sha256", "epoch_semantics", "source"}
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
_IDENTIFIER_KEYS = {"catalog", "id", "version"}
_PROVENANCE_ENTRY_KEYS = {"source", "uncertainty", "unit"}
_COVARIANCE_KEYS = {"parameters", "units", "kind", "matrix"}
_ACCELERATION_KEYS = {"accel_ra_cosdec_mas_per_yr2", "accel_dec_mas_per_yr2", "source"}
_ORBIT_KEYS = {
    "period_yr",
    "periastron_epoch_jyear",
    "eccentricity",
    "semimajor_axis_arcsec",
    "inclination_deg",
    "ascending_node_deg",
    "arg_periastron_deg",
    "mass_fraction_secondary",
    "component",
    "source",
}
#: Astrometry fields that carry a measured value (per-value provenance may
#: reference these plus the acceleration/orbit numeric fields present on the
#: same target).
_ASTROMETRY_VALUE_KEYS = {
    "ra_deg",
    "dec_deg",
    "parallax_mas",
    "distance_pc",
    "pm_ra_cosdec_mas_per_yr",
    "pm_dec_mas_per_yr",
    "radial_velocity_km_s",
    "reference_epoch_jyear",
}
_ACCELERATION_VALUE_KEYS = _ACCELERATION_KEYS - {"source"}
_ORBIT_VALUE_KEYS = _ORBIT_KEYS - {"source", "component"}


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

        ``None`` values and empty optional blocks are omitted; this dict
        (dumped as YAML) is itself a valid registry file.
        """
        targets: dict[str, Any] = {}
        for target in sorted(self.targets, key=lambda t: t.target_id):
            targets[target.target_id] = _normalized_target(target)
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


def _normalized_astrometry(state: AstrometricState) -> dict[str, Any]:
    astrometry: dict[str, Any] = {
        "frame": state.frame,
        "ra_deg": state.ra_deg,
        "dec_deg": state.dec_deg,
        "pm_ra_cosdec_mas_per_yr": state.pm_ra_cosdec_mas_per_yr,
        "pm_dec_mas_per_yr": state.pm_dec_mas_per_yr,
        "reference_epoch_jyear": state.reference_epoch_jyear,
        "reference_epoch_scale": state.reference_epoch_scale,
        "source": state.source,
    }
    if state.parallax_mas is not None:
        astrometry["parallax_mas"] = state.parallax_mas
    if state.distance_pc is not None:
        astrometry["distance_pc"] = state.distance_pc
    if state.radial_velocity_km_s is not None:
        astrometry["radial_velocity_km_s"] = state.radial_velocity_km_s
    return astrometry


def _normalized_target_common(target: Target) -> dict[str, Any]:
    return {
        "display_name": target.display_name,
        "endpoint_kind": target.endpoint_kind.value,
        "priority": target.priority,
        "tags": list(target.tags),
        "flags": list(target.flags),
        "notes": target.notes,
    }


def _normalized_target(target: Target) -> dict[str, Any]:
    state: dict[str, Any] = {
        "provider": target.provider_id,
        "astrometry": _normalized_astrometry(target.astrometry),
    }
    if target.parameter_provenance:
        provenance: dict[str, Any] = {}
        for entry in sorted(target.parameter_provenance, key=lambda e: e.parameter):
            record: dict[str, Any] = {"source": entry.source}
            if entry.uncertainty is not None:
                record["uncertainty"] = entry.uncertainty
                record["unit"] = entry.unit
            provenance[entry.parameter] = record
        state["provenance"] = provenance
    if target.covariance is not None:
        state["covariance"] = {
            "parameters": list(target.covariance.parameters),
            "units": list(target.covariance.units),
            "kind": target.covariance.kind.value,
            "matrix": [list(row) for row in target.covariance.matrix],
        }
    if target.acceleration is not None:
        state["acceleration"] = {
            "accel_ra_cosdec_mas_per_yr2": target.acceleration.accel_ra_cosdec_mas_per_yr2,
            "accel_dec_mas_per_yr2": target.acceleration.accel_dec_mas_per_yr2,
            "source": target.acceleration.source,
        }
    if target.orbit is not None:
        state["orbit"] = {
            "period_yr": target.orbit.period_yr,
            "periastron_epoch_jyear": target.orbit.periastron_epoch_jyear,
            "eccentricity": target.orbit.eccentricity,
            "semimajor_axis_arcsec": target.orbit.semimajor_axis_arcsec,
            "inclination_deg": target.orbit.inclination_deg,
            "ascending_node_deg": target.orbit.ascending_node_deg,
            "arg_periastron_deg": target.orbit.arg_periastron_deg,
            "mass_fraction_secondary": target.orbit.mass_fraction_secondary,
            "component": target.orbit.component.value,
            "source": target.orbit.source,
        }
    if target.sampled_state is not None:
        state["sampled_state"] = {
            "path": target.sampled_state.path,
            "checksum_sha256": target.sampled_state.checksum_sha256,
            "epoch_semantics": target.sampled_state.epoch_semantics,
            "source": target.sampled_state.source,
        }
    normalized = _normalized_target_common(target)
    if target.identifiers:
        normalized["identifiers"] = [
            {"catalog": ident.catalog, "id": ident.identifier, "version": ident.version}
            for ident in target.identifiers
        ]
    if target.quality:
        normalized["quality"] = target.quality
    if target.model_rationale:
        normalized["model_rationale"] = target.model_rationale
    normalized["state"] = state
    return normalized


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
        targets.append(
            _parse_target(target_id, block, ctx, fail, missing_radial_velocity)
        )

    return TargetRegistry.from_targets(tuple(targets))


def _parse_target(
    target_id: str,
    block: dict[str, Any],
    ctx: str,
    fail: _Fail,
    missing_radial_velocity: Literal["error", "flag"],
) -> Target:
    _check_keys(block, _TARGET_KEYS, ctx, fail)
    state_ctx = f"{ctx}.state"
    state_block = _mapping(block.get("state"), state_ctx, fail)
    _check_keys(state_block, _STATE_KEYS, state_ctx, fail)

    provider = state_block.get("provider")
    if not isinstance(provider, str) or provider not in SUPPORTED_TARGET_STATE_PROVIDERS:
        fail(
            f"{state_ctx}.provider",
            f"is required; choose from {sorted(SUPPORTED_TARGET_STATE_PROVIDERS)}",
        )

    astro_ctx = f"{state_ctx}.astrometry"
    astro = _mapping(state_block.get("astrometry"), astro_ctx, fail)
    flags = _parse_str_tuple(block.get("flags", []), f"{ctx}.flags", fail)
    astrometry, flags = _parse_astrometry(
        astro, astro_ctx, fail, missing_radial_velocity, flags
    )

    acceleration: AccelerationTerms | None = None
    if "acceleration" in state_block:
        accel_ctx = f"{state_ctx}.acceleration"
        accel = _mapping(state_block.get("acceleration"), accel_ctx, fail)
        _check_keys(accel, _ACCELERATION_KEYS, accel_ctx, fail)
        acceleration = _build(
            accel_ctx,
            fail,
            AccelerationTerms,
            accel_ra_cosdec_mas_per_yr2=_number(
                accel, "accel_ra_cosdec_mas_per_yr2", accel_ctx, fail
            ),
            accel_dec_mas_per_yr2=_number(accel, "accel_dec_mas_per_yr2", accel_ctx, fail),
            source=_string(accel, "source", accel_ctx, fail),
        )

    orbit: OrbitSolution | None = None
    if "orbit" in state_block:
        orbit_ctx = f"{state_ctx}.orbit"
        orbit_block = _mapping(state_block.get("orbit"), orbit_ctx, fail)
        _check_keys(orbit_block, _ORBIT_KEYS, orbit_ctx, fail)
        component_raw = orbit_block.get("component")
        if not isinstance(component_raw, str):
            fail(
                f"{orbit_ctx}.component",
                f"is required; choose from {[c.value for c in OrbitComponent]}",
            )
        try:
            component = OrbitComponent(component_raw.strip().lower())
        except ValueError:
            fail(
                f"{orbit_ctx}.component",
                f"unknown component {component_raw!r}; "
                f"choose from {[c.value for c in OrbitComponent]}",
            )
        orbit = _build(
            orbit_ctx,
            fail,
            OrbitSolution,
            period_yr=_number(orbit_block, "period_yr", orbit_ctx, fail),
            periastron_epoch_jyear=_number(
                orbit_block, "periastron_epoch_jyear", orbit_ctx, fail
            ),
            eccentricity=_number(orbit_block, "eccentricity", orbit_ctx, fail),
            semimajor_axis_arcsec=_number(
                orbit_block, "semimajor_axis_arcsec", orbit_ctx, fail
            ),
            inclination_deg=_number(orbit_block, "inclination_deg", orbit_ctx, fail),
            ascending_node_deg=_number(orbit_block, "ascending_node_deg", orbit_ctx, fail),
            arg_periastron_deg=_number(orbit_block, "arg_periastron_deg", orbit_ctx, fail),
            mass_fraction_secondary=_number(
                orbit_block, "mass_fraction_secondary", orbit_ctx, fail
            ),
            component=component,
            source=_string(orbit_block, "source", orbit_ctx, fail),
        )

    sampled_state: SampledStateSpec | None = None
    if "sampled_state" in state_block:
        sampled_ctx = f"{state_ctx}.sampled_state"
        sampled_block = _mapping(state_block.get("sampled_state"), sampled_ctx, fail)
        _check_keys(sampled_block, _SAMPLED_STATE_KEYS, sampled_ctx, fail)
        sampled_state = _build(
            sampled_ctx,
            fail,
            SampledStateSpec,
            path=_string(sampled_block, "path", sampled_ctx, fail),
            checksum_sha256=_string(sampled_block, "checksum_sha256", sampled_ctx, fail),
            epoch_semantics=_string(sampled_block, "epoch_semantics", sampled_ctx, fail),
            source=_string(sampled_block, "source", sampled_ctx, fail),
        )

    parameter_provenance = _parse_provenance(
        state_block,
        f"{state_ctx}.provenance",
        fail,
        present_values=_present_value_keys(astro, acceleration, orbit),
    )
    covariance = _parse_covariance(state_block, f"{state_ctx}.covariance", fail)
    identifiers = _parse_identifiers(block, f"{ctx}.identifiers", fail)
    endpoint_kind = _parse_endpoint_kind(block, ctx, fail)
    priority = _number(block, "priority", ctx, fail) if "priority" in block else 1.0
    quality = str(block.get("quality", ""))
    model_rationale = str(block.get("model_rationale", ""))

    target: Target = _build(
        ctx,
        fail,
        Target,
        target_id=target_id,
        display_name=str(block.get("display_name", target_id)),
        endpoint_kind=endpoint_kind,
        astrometry=astrometry,
        priority=priority,
        tags=_parse_str_tuple(block.get("tags", []), f"{ctx}.tags", fail),
        flags=flags,
        notes=str(block.get("notes", "")),
        provider_id=provider,
        acceleration=acceleration,
        orbit=orbit,
        sampled_state=sampled_state,
        identifiers=identifiers,
        parameter_provenance=parameter_provenance,
        covariance=covariance,
        quality=quality,
        model_rationale=model_rationale,
    )
    return target


def _parse_astrometry(
    astro: dict[str, Any],
    astro_ctx: str,
    fail: _Fail,
    missing_radial_velocity: Literal["error", "flag"],
    flags: tuple[str, ...],
) -> tuple[AstrometricState, tuple[str, ...]]:
    _check_keys(astro, _ASTROMETRY_KEYS, astro_ctx, fail)

    frame = astro.get("frame")
    if not isinstance(frame, str):
        fail(f"{astro_ctx}.frame", "is required (v1 supports only 'icrs')")
    for required in ("reference_epoch_scale", "source"):
        if not isinstance(astro.get(required), str) or not str(astro[required]).strip():
            fail(f"{astro_ctx}.{required}", "is required and must be a non-empty string")

    parallax = (
        _number(astro, "parallax_mas", astro_ctx, fail) if "parallax_mas" in astro else None
    )
    distance = (
        _number(astro, "distance_pc", astro_ctx, fail) if "distance_pc" in astro else None
    )

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
    return state, flags


def _parse_endpoint_kind(block: dict[str, Any], ctx: str, fail: _Fail) -> EndpointKind:
    endpoint_raw = block.get("endpoint_kind")
    if not isinstance(endpoint_raw, str):
        fail(
            f"{ctx}.endpoint_kind",
            f"is required; choose from {[k.value for k in EndpointKind]}",
        )
    try:
        return EndpointKind(endpoint_raw.strip().lower())
    except ValueError:
        fail(
            f"{ctx}.endpoint_kind",
            f"unknown kind {endpoint_raw!r}; choose from {[k.value for k in EndpointKind]}",
        )


def _present_value_keys(
    astro: dict[str, Any],
    acceleration: AccelerationTerms | None,
    orbit: OrbitSolution | None,
) -> set[str]:
    present = _ASTROMETRY_VALUE_KEYS.intersection(astro)
    if acceleration is not None:
        present |= _ACCELERATION_VALUE_KEYS
    if orbit is not None:
        present |= _ORBIT_VALUE_KEYS
    return present


def _parse_provenance(
    state_block: dict[str, Any],
    ctx: str,
    fail: _Fail,
    *,
    present_values: set[str],
) -> tuple[ParameterProvenance, ...]:
    if "provenance" not in state_block:
        return ()
    raw = _mapping(state_block.get("provenance"), ctx, fail)
    entries: list[ParameterProvenance] = []
    for parameter, entry_raw in raw.items():
        entry_ctx = f"{ctx}.{parameter}"
        if not isinstance(parameter, str) or parameter not in present_values:
            fail(
                ctx,
                f"provenance parameter {parameter!r} does not name a value "
                f"present in this target's solution; present: {sorted(present_values)}",
            )
        entry = _mapping(entry_raw, entry_ctx, fail)
        _check_keys(entry, _PROVENANCE_ENTRY_KEYS, entry_ctx, fail)
        uncertainty = (
            _number(entry, "uncertainty", entry_ctx, fail)
            if "uncertainty" in entry
            else None
        )
        unit = _string(entry, "unit", entry_ctx, fail) if "unit" in entry else None
        entries.append(
            _build(
                entry_ctx,
                fail,
                ParameterProvenance,
                parameter=parameter,
                source=_string(entry, "source", entry_ctx, fail),
                uncertainty=uncertainty,
                unit=unit,
            )
        )
    return tuple(sorted(entries, key=lambda e: e.parameter))


def _parse_covariance(
    state_block: dict[str, Any], ctx: str, fail: _Fail
) -> CovarianceSpec | None:
    if "covariance" not in state_block:
        return None
    raw = _mapping(state_block.get("covariance"), ctx, fail)
    _check_keys(raw, _COVARIANCE_KEYS, ctx, fail)
    parameters = _parse_str_tuple(raw.get("parameters", []), f"{ctx}.parameters", fail)
    units = _parse_str_tuple(raw.get("units", []), f"{ctx}.units", fail, allow_duplicates=True)
    kind_raw = raw.get("kind", "covariance")
    try:
        kind = CovarianceKind(str(kind_raw).strip().lower())
    except ValueError:
        fail(
            f"{ctx}.kind",
            f"unknown kind {kind_raw!r}; choose from {[k.value for k in CovarianceKind]}",
        )
    matrix_raw = raw.get("matrix")
    if not isinstance(matrix_raw, list) or not all(
        isinstance(row, list) for row in matrix_raw
    ):
        fail(f"{ctx}.matrix", "must be a list of rows (lists of numbers)")
    matrix: list[tuple[float, ...]] = []
    for i, row in enumerate(matrix_raw):
        values: list[float] = []
        for j, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                fail(f"{ctx}.matrix", f"entry [{i}][{j}] must be a number, got {value!r}")
            values.append(float(value))
        matrix.append(tuple(values))
    covariance: CovarianceSpec = _build(
        ctx,
        fail,
        CovarianceSpec,
        parameters=parameters,
        units=units,
        matrix=tuple(matrix),
        kind=kind,
    )
    return covariance


def _parse_identifiers(
    block: dict[str, Any], ctx: str, fail: _Fail
) -> tuple[CatalogIdentifier, ...]:
    if "identifiers" not in block:
        return ()
    raw = block.get("identifiers")
    if not isinstance(raw, list):
        fail(ctx, "must be a list of {catalog, id, version} mappings")
    identifiers: list[CatalogIdentifier] = []
    for index, entry_raw in enumerate(raw):
        entry_ctx = f"{ctx}[{index}]"
        entry = _mapping(entry_raw, entry_ctx, fail)
        _check_keys(entry, _IDENTIFIER_KEYS, entry_ctx, fail)
        identifiers.append(
            _build(
                entry_ctx,
                fail,
                CatalogIdentifier,
                catalog=_string(entry, "catalog", entry_ctx, fail),
                identifier=_string(entry, "id", entry_ctx, fail),
                version=_string(entry, "version", entry_ctx, fail),
            )
        )
    return tuple(identifiers)


def _parse_str_tuple(
    raw: Any, ctx: str, fail: _Fail, *, allow_duplicates: bool = False
) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        fail(ctx, "must be a list of strings")
    items = tuple(str(item).strip() for item in raw)
    if not allow_duplicates and len(set(items)) != len(items):
        fail(ctx, "must not contain duplicates")
    return items
