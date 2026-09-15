"""Typed immutable inputs and result records.

This module defines the stable scientific boundary of sglseti: enums and
frozen dataclasses for every input and result concept. It imports no other
application module and, deliberately, no astropy at module level — quantity
coercion is duck-typed via ``to_value`` so that validation-only workflows
(``sglseti validate``, ``sglseti samples``) do not pay for heavy scientific
imports. Geometry modules (Phase 4) import astropy normally.

Domain objects validate their own invariants in ``__post_init__`` and raise
``ValueError`` with a field-specific message; the config layer wraps those
into :class:`~sglseti.errors.ConfigError` with file/path context.

Result records use plain floats with unit-suffixed field names so exports are
deterministic; inputs accept astropy ``Quantity``/``Time`` at the public API.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astropy.time import Time

__all__ = [
    "SUPPORTED_MODEL_IDS",
    "SUPPORTED_TARGET_STATE_PROVIDERS",
    "AccelerationTerms",
    "AdaptiveLocus",
    "AstrometricState",
    "BeamSide",
    "CatalogIdentifier",
    "CovarianceKind",
    "CovarianceSpec",
    "IntervalState",
    "LocusPoint",
    "ObservationInterval",
    "OrbitComponent",
    "OrbitSolution",
    "ParameterProvenance",
    "SampledStateSpec",
    "SweptLocus",
    "ZInterval",
    "BeamWindow",
    "CalculationResult",
    "CoordinateProduct",
    "CorrectionType",
    "Corridor",
    "CrossingEvent",
    "CrossingsRequest",
    "CrossingsResult",
    "DirectionSolution",
    "EndpointKind",
    "Epoch",
    "EphemerisAdapter",
    "EphemerisSpec",
    "FieldOfView",
    "GeometryRequest",
    "ImpactSample",
    "LinkDirection",
    "LocusSample",
    "ObservabilityConstraints",
    "Observer",
    "ObserverKind",
    "OutputFormat",
    "Pointing",
    "RangeSegment",
    "RelayRange",
    "Role",
    "SamplingKind",
    "SamplingSpec",
    "Target",
    "TargetEventKind",
    "TimeGrid",
    "TimeInterval",
    "TimeIntervals",
    "TimeList",
    "TimeSingle",
    "UncertaintyMethod",
    "Validity",
    "VisibilitySample",
]

#: Geometry model IDs implemented by v1. Unknown IDs fail request validation.
SUPPORTED_MODEL_IDS = frozenset({"tusay2022_eq5_7_v1"})

#: Time scales accepted for a target catalog's reference epoch. Gaia uses TCB.
SUPPORTED_REFERENCE_EPOCH_SCALES = frozenset({"tcb", "tdb", "tt", "tai", "utc"})

#: Registry flags the linear-motion family cannot model. Their presence on a
#: ``linear_astrometry_v1`` target is a validation error rather than a
#: silently degraded result; the acceleration and orbital families accept
#: them because modeling that motion is exactly their purpose.
UNSUPPORTED_TARGET_FLAGS = frozenset({"unresolved_binary", "accelerating_system"})

#: Target-state provider families selectable by registry schema v2 (roadmap
#: §2.1). Schema-v1 targets are always ``linear_astrometry_v1``.
SUPPORTED_TARGET_STATE_PROVIDERS = frozenset(
    {
        "linear_astrometry_v1",
        "acceleration_astrometry_v1",
        "two_body_orbit_v1",
        "sampled_state_v1",
    }
)

#: Endpoint kinds each provider family can model. ``planet`` endpoints are
#: modeled only by ``sampled_state_v1`` (an external ephemeris can position
#: any moving endpoint); ``other`` appears in the schema for forward
#: compatibility but remains rejected at validation time.
PROVIDER_ENDPOINT_KINDS = {
    "linear_astrometry_v1": frozenset({"star", "component", "barycenter"}),
    "acceleration_astrometry_v1": frozenset({"star", "component", "barycenter"}),
    "two_body_orbit_v1": frozenset({"component", "barycenter"}),
    "sampled_state_v1": frozenset({"star", "component", "barycenter", "planet"}),
}

#: Epoch-semantics declarations a sampled-state ephemeris may carry. The v1
#: geometry model consumes only arrival-indexed states; declaring
#: ``physical_event_time`` documents a table the model will explicitly
#: refuse rather than silently misinterpret.
SUPPORTED_SAMPLED_EPOCH_SEMANTICS = frozenset({"ssb_light_arrival_time", "physical_event_time"})

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_EPOCH_ID_PATTERN = re.compile(r"^\S+$")


class Role(StrEnum):
    ANTIPODE = "antipode"
    RX = "rx"
    TX = "tx"


class LinkDirection(StrEnum):
    """Which leg of the hypothesized relay link a beam crossing samples.

    ``inbound`` is the home-star-to-relay uplink; ``outbound`` is the
    relay-to-home-star downlink. Each maps to a fixed catalog direction
    epoch in the crossing axis model (ADR-0003), not a free parameter.
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class BeamSide(StrEnum):
    """Which side of the Sun the observer is on along the beam axis."""

    TARGET = "target"
    ANTI_TARGET = "anti_target"


class EndpointKind(StrEnum):
    STAR = "star"
    COMPONENT = "component"
    BARYCENTER = "barycenter"
    PLANET = "planet"
    OTHER = "other"


class OrbitComponent(StrEnum):
    """Which point of a two-body system an orbital solution positions."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    BARYCENTER = "barycenter"


class CovarianceKind(StrEnum):
    COVARIANCE = "covariance"
    CORRELATION = "correlation"


class Validity(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


class UncertaintyMethod(StrEnum):
    NOT_PROPAGATED = "not_propagated"
    ASSUMED = "assumed"
    PROPAGATED = "propagated"


class CorrectionType(StrEnum):
    GEOMETRIC = "geometric"
    CIRS_APPARENT = "cirs_apparent"
    ALTAZ_APPARENT = "altaz_apparent"


class TargetEventKind(StrEnum):
    EMISSION = "emission"
    ARRIVAL = "arrival"
    APPARENT_STATE = "apparent_state"


class ObserverKind(StrEnum):
    EARTH_CENTER = "earth_center"
    SITE = "site"
    # Registry of observer-state provider families (roadmap §2.4); each
    # kind maps 1:1 onto a provider family in :mod:`sglseti.providers`.
    SOLAR_SYSTEM_BODY = "solar_system_body"
    SPACECRAFT_TABLE = "spacecraft_table"
    SPACECRAFT_SPICE = "spacecraft_spice"
    PROGRAMMATIC = "programmatic"


class SamplingKind(StrEnum):
    COUNT = "count"
    RECIPROCAL_STEP = "reciprocal_step"
    EXPLICIT = "explicit"


class EphemerisAdapter(StrEnum):
    ASTROPY_BUILTIN = "astropy_builtin"
    JPL_FILE = "jpl_file"


class CoordinateProduct(StrEnum):
    ICRS = "icrs"
    CIRS = "cirs"
    ALTAZ = "altaz"


class OutputFormat(StrEnum):
    ECSV = "ecsv"
    JSON = "json"
    CSV = "csv"
    DS9 = "ds9"
    VOTABLE = "votable"


def _require_finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _quantity_value(value: object, unit: str, name: str) -> float:
    """Coerce a plain number or an astropy Quantity to a float in ``unit``.

    Duck-typed via ``to_value`` so this module never imports astropy.
    """
    to_value = getattr(value, "to_value", None)
    if callable(to_value):
        try:
            converted = float(to_value(unit))
        except Exception as exc:
            raise ValueError(f"{name} could not be converted to {unit}: {exc}") from exc
        return _require_finite(name, converted)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or a Quantity convertible to {unit}")
    return _require_finite(name, float(value))


# ---------------------------------------------------------------------------
# Input objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AstrometricState:
    """ICRS catalog astrometry with explicit epoch, scale, and provenance.

    Exactly one of ``parallax_mas`` and ``distance_pc`` must be given.
    ``radial_velocity_km_s`` may be ``None`` only when the loader was told to
    flag a missing radial velocity instead of rejecting it; it is never
    silently replaced with zero.
    """

    ra_deg: float
    dec_deg: float
    pm_ra_cosdec_mas_per_yr: float
    pm_dec_mas_per_yr: float
    reference_epoch_jyear: float
    reference_epoch_scale: str
    source: str
    parallax_mas: float | None = None
    distance_pc: float | None = None
    radial_velocity_km_s: float | None = None
    frame: str = "icrs"

    def __post_init__(self) -> None:
        _require_finite("ra_deg", self.ra_deg)
        _require_finite("dec_deg", self.dec_deg)
        if not 0.0 <= self.ra_deg < 360.0:
            raise ValueError(f"ra_deg must be within [0, 360), got {self.ra_deg}")
        if not -90.0 <= self.dec_deg <= 90.0:
            raise ValueError(f"dec_deg must be within [-90, 90], got {self.dec_deg}")
        _require_finite("pm_ra_cosdec_mas_per_yr", self.pm_ra_cosdec_mas_per_yr)
        _require_finite("pm_dec_mas_per_yr", self.pm_dec_mas_per_yr)
        _require_finite("reference_epoch_jyear", self.reference_epoch_jyear)
        if not 1800.0 <= self.reference_epoch_jyear <= 2200.0:
            raise ValueError(
                "reference_epoch_jyear must be within [1800, 2200], "
                f"got {self.reference_epoch_jyear}"
            )
        if self.reference_epoch_scale not in SUPPORTED_REFERENCE_EPOCH_SCALES:
            raise ValueError(
                f"reference_epoch_scale must be one of "
                f"{sorted(SUPPORTED_REFERENCE_EPOCH_SCALES)}, "
                f"got {self.reference_epoch_scale!r}"
            )
        if (self.parallax_mas is None) == (self.distance_pc is None):
            raise ValueError("exactly one of parallax_mas and distance_pc is required")
        if self.parallax_mas is not None:
            _require_finite("parallax_mas", self.parallax_mas)
            if self.parallax_mas <= 0.0:
                raise ValueError(f"parallax_mas must be positive, got {self.parallax_mas}")
        if self.distance_pc is not None:
            _require_finite("distance_pc", self.distance_pc)
            if self.distance_pc <= 0.0:
                raise ValueError(f"distance_pc must be positive, got {self.distance_pc}")
        if self.radial_velocity_km_s is not None:
            _require_finite("radial_velocity_km_s", self.radial_velocity_km_s)
        if self.frame != "icrs":
            raise ValueError(f"frame must be 'icrs' in v1, got {self.frame!r}")
        if not self.source or self.source.strip().lower() == "unspecified":
            raise ValueError("source must be a non-empty, real provenance statement")


def _require_source(value: str, name: str = "source") -> str:
    if not value or value.strip().lower() == "unspecified":
        raise ValueError(f"{name} must be a non-empty, real provenance statement")
    return value


@dataclass(frozen=True)
class CatalogIdentifier:
    """An immutable catalog or literature identifier for an adopted solution.

    ``version`` pins the release (e.g. ``"DR3"``, ``"2016, A&A 586, A90"``)
    so the identifier can never silently drift to a newer solution.
    """

    catalog: str
    identifier: str
    version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("catalog", self.catalog),
            ("identifier", self.identifier),
            ("version", self.version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"identifier {name} must be a non-empty string")


@dataclass(frozen=True)
class ParameterProvenance:
    """Per-value provenance for one adopted solution parameter.

    ``uncertainty`` is a 1-sigma value in the declared ``unit`` — the unit is
    mandatory whenever an uncertainty is given so a bare number can never
    masquerade as being in the parameter's storage unit.
    """

    parameter: str
    source: str
    uncertainty: float | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.parameter or not self.parameter.strip():
            raise ValueError("provenance parameter name must be non-empty")
        _require_source(self.source, f"provenance source for {self.parameter}")
        if self.uncertainty is not None:
            _require_finite(f"uncertainty for {self.parameter}", self.uncertainty)
            if self.uncertainty <= 0.0:
                raise ValueError(
                    f"uncertainty for {self.parameter} must be positive, got {self.uncertainty}"
                )
            if not self.unit or not self.unit.strip():
                raise ValueError(f"uncertainty for {self.parameter} requires an explicit unit")


@dataclass(frozen=True)
class CovarianceSpec:
    """A full covariance or correlation matrix with declared ordering.

    ``parameters`` and ``units`` fix the row/column ordering and units
    explicitly — the matrix is meaningless without them, so they are part of
    the record rather than a convention.
    """

    parameters: tuple[str, ...]
    units: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    kind: CovarianceKind = CovarianceKind.COVARIANCE

    def __post_init__(self) -> None:
        n = len(self.parameters)
        if n == 0:
            raise ValueError("covariance parameters must be non-empty")
        if len(set(self.parameters)) != n:
            raise ValueError("covariance parameters must be unique")
        if any(not p or not p.strip() for p in self.parameters):
            raise ValueError("covariance parameters must be non-empty strings")
        if len(self.units) != n:
            raise ValueError(f"covariance declares {n} parameters but {len(self.units)} units")
        if any(not isinstance(unit, str) or not unit.strip() for unit in self.units):
            raise ValueError("covariance units must be non-empty strings")
        if len(self.matrix) != n:
            raise ValueError(f"covariance matrix must have {n} rows, got {len(self.matrix)}")
        for i, row in enumerate(self.matrix):
            if len(row) != n:
                raise ValueError(f"covariance matrix row {i} must have {n} entries, got {len(row)}")
            for j, value in enumerate(row):
                _require_finite(f"covariance matrix[{i}][{j}]", value)
        for i in range(n):
            for j in range(i):
                if self.matrix[i][j] != self.matrix[j][i]:
                    raise ValueError(
                        f"covariance matrix must be symmetric; "
                        f"[{i}][{j}]={self.matrix[i][j]} != [{j}][{i}]={self.matrix[j][i]}"
                    )
        for i in range(n):
            diagonal = self.matrix[i][i]
            if self.kind is CovarianceKind.CORRELATION:
                if diagonal != 1.0:
                    raise ValueError(
                        f"correlation matrix diagonal must be exactly 1, "
                        f"got {diagonal} at [{i}][{i}]"
                    )
            elif diagonal <= 0.0:
                raise ValueError(
                    f"covariance matrix diagonal must be positive, got {diagonal} at [{i}][{i}]"
                )
        if self.kind is CovarianceKind.CORRELATION:
            for i in range(n):
                for j in range(i):
                    if not -1.0 <= self.matrix[i][j] <= 1.0:
                        raise ValueError(
                            f"correlation entries must be within [-1, 1], "
                            f"got {self.matrix[i][j]} at [{i}][{j}]"
                        )


@dataclass(frozen=True)
class AccelerationTerms:
    """Catalog astrometric acceleration (quadratic proper-motion terms).

    The sky-plane acceleration of e.g. a Hipparcos-Gaia or Gaia 7/9-parameter
    solution, applied about the same reference epoch as the linear state.
    """

    accel_ra_cosdec_mas_per_yr2: float
    accel_dec_mas_per_yr2: float
    source: str

    def __post_init__(self) -> None:
        _require_finite("accel_ra_cosdec_mas_per_yr2", self.accel_ra_cosdec_mas_per_yr2)
        _require_finite("accel_dec_mas_per_yr2", self.accel_dec_mas_per_yr2)
        _require_source(self.source, "acceleration source")


@dataclass(frozen=True)
class OrbitSolution:
    """A published visual-binary (Campbell) orbital solution.

    Elements describe the RELATIVE orbit of the secondary about the primary
    (the standard visual-binary convention: position angles east of north,
    ``periastron_epoch_jyear`` in observation-date years, i.e. the same
    light-arrival-indexed convention as catalog astrometry).
    ``mass_fraction_secondary`` is ``M_secondary / (M_primary + M_secondary)``
    and scales the component orbits about the barycenter; ``component``
    selects which point of the system this target is.
    """

    period_yr: float
    periastron_epoch_jyear: float
    eccentricity: float
    semimajor_axis_arcsec: float
    inclination_deg: float
    ascending_node_deg: float
    arg_periastron_deg: float
    mass_fraction_secondary: float
    component: OrbitComponent
    source: str

    def __post_init__(self) -> None:
        _require_finite("period_yr", self.period_yr)
        if self.period_yr <= 0.0:
            raise ValueError(f"period_yr must be positive, got {self.period_yr}")
        _require_finite("periastron_epoch_jyear", self.periastron_epoch_jyear)
        if not 1500.0 <= self.periastron_epoch_jyear <= 2500.0:
            raise ValueError(
                "periastron_epoch_jyear must be within [1500, 2500], "
                f"got {self.periastron_epoch_jyear}"
            )
        _require_finite("eccentricity", self.eccentricity)
        if not 0.0 <= self.eccentricity < 1.0:
            raise ValueError(f"eccentricity must be within [0, 1), got {self.eccentricity}")
        _require_finite("semimajor_axis_arcsec", self.semimajor_axis_arcsec)
        if self.semimajor_axis_arcsec <= 0.0:
            raise ValueError(
                f"semimajor_axis_arcsec must be positive, got {self.semimajor_axis_arcsec}"
            )
        _require_finite("inclination_deg", self.inclination_deg)
        if not 0.0 <= self.inclination_deg <= 180.0:
            raise ValueError(f"inclination_deg must be within [0, 180], got {self.inclination_deg}")
        for name, value in (
            ("ascending_node_deg", self.ascending_node_deg),
            ("arg_periastron_deg", self.arg_periastron_deg),
        ):
            _require_finite(name, value)
            if not 0.0 <= value < 360.0:
                raise ValueError(f"{name} must be within [0, 360), got {value}")
        _require_finite("mass_fraction_secondary", self.mass_fraction_secondary)
        if not 0.0 < self.mass_fraction_secondary < 1.0:
            raise ValueError(
                f"mass_fraction_secondary must be within (0, 1), got {self.mass_fraction_secondary}"
            )
        _require_source(self.source, "orbit source")


@dataclass(frozen=True)
class SampledStateSpec:
    """An externally generated, checksummed target ephemeris (§2.1).

    ``path`` points to an ECSV table of barycentric ICRS positions
    (``epoch_tdb_jd``, ``x_au``/``y_au``/``z_au``, optional velocity
    columns for cubic-Hermite interpolation). ``checksum_sha256`` is
    REQUIRED — the family is named for it: the registry pins the adopted
    solution by content, and identities never carry the path.
    ``epoch_semantics`` declares how the table's epochs are indexed; the
    v1 geometry model refuses anything but ``ssb_light_arrival_time``.
    """

    path: str
    checksum_sha256: str
    epoch_semantics: str
    source: str

    def __post_init__(self) -> None:
        if not self.path or not self.path.strip():
            raise ValueError("sampled_state requires a path")
        if not self.checksum_sha256 or not self.checksum_sha256.strip():
            raise ValueError(
                "sampled_state requires checksum_sha256: the family exists "
                "for CHECKSUMMED external ephemerides (improvements §2.1)"
            )
        if self.epoch_semantics not in SUPPORTED_SAMPLED_EPOCH_SEMANTICS:
            raise ValueError(
                f"sampled_state epoch_semantics must be one of "
                f"{sorted(SUPPORTED_SAMPLED_EPOCH_SEMANTICS)}, "
                f"got {self.epoch_semantics!r}"
            )
        _require_source(self.source, "sampled_state source")


@dataclass(frozen=True)
class Target:
    """A curated stellar-system endpoint with validated astrometry.

    ``provider_id`` selects the target-state provider family (registry
    schema v2); schema-v1 targets are always ``linear_astrometry_v1``. For
    ``two_body_orbit_v1``, ``astrometry`` describes the system BARYCENTER
    and ``orbit`` positions the endpoint relative to it."""

    target_id: str
    display_name: str
    endpoint_kind: EndpointKind
    astrometry: AstrometricState
    priority: float = 1.0
    tags: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    notes: str = ""
    # Registry schema v2 (roadmap §2.2): provider selection, richer motion
    # models, and per-value provenance. Defaults are exactly the v1 target.
    provider_id: str = "linear_astrometry_v1"
    acceleration: AccelerationTerms | None = None
    orbit: OrbitSolution | None = None
    # For sampled_state_v1 targets the ``astrometry`` block is the
    # APPROXIMATE reference solution (used for readability and a load-time
    # consistency check); the checksummed table is the adopted solution.
    sampled_state: SampledStateSpec | None = None
    identifiers: tuple[CatalogIdentifier, ...] = ()
    parameter_provenance: tuple[ParameterProvenance, ...] = ()
    covariance: CovarianceSpec | None = None
    quality: str = ""
    model_rationale: str = ""

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.target_id):
            raise ValueError(
                f"target_id must match {_ID_PATTERN.pattern!r}, got {self.target_id!r}"
            )
        if not self.display_name:
            raise ValueError("display_name must be non-empty")
        if self.provider_id not in SUPPORTED_TARGET_STATE_PROVIDERS:
            raise ValueError(
                f"unknown target-state provider {self.provider_id!r}; "
                f"supported: {sorted(SUPPORTED_TARGET_STATE_PROVIDERS)}"
            )
        allowed_kinds = PROVIDER_ENDPOINT_KINDS[self.provider_id]
        if self.endpoint_kind.value not in allowed_kinds:
            raise ValueError(
                f"endpoint_kind {self.endpoint_kind.value!r} is not modeled by "
                f"provider {self.provider_id!r} (allowed: {sorted(allowed_kinds)}); "
                "'planet' endpoints are modeled only by sampled_state_v1 and "
                "'other' awaits a future provider family"
            )
        needs_orbit = self.provider_id == "two_body_orbit_v1"
        if needs_orbit != (self.orbit is not None):
            raise ValueError(
                "an orbit solution is required by (and only by) provider "
                f"'two_body_orbit_v1'; provider is {self.provider_id!r} and "
                f"orbit is {'present' if self.orbit else 'absent'}"
            )
        needs_accel = self.provider_id == "acceleration_astrometry_v1"
        if needs_accel != (self.acceleration is not None):
            raise ValueError(
                "acceleration terms are required by (and only by) provider "
                f"'acceleration_astrometry_v1'; provider is {self.provider_id!r} "
                f"and acceleration is {'present' if self.acceleration else 'absent'}"
            )
        needs_sampled = self.provider_id == "sampled_state_v1"
        if needs_sampled != (self.sampled_state is not None):
            raise ValueError(
                "a sampled_state spec is required by (and only by) provider "
                f"'sampled_state_v1'; provider is {self.provider_id!r} and "
                f"sampled_state is {'present' if self.sampled_state else 'absent'}"
            )
        if self.orbit is not None:
            barycenter_endpoint = self.endpoint_kind is EndpointKind.BARYCENTER
            barycenter_component = self.orbit.component is OrbitComponent.BARYCENTER
            if barycenter_endpoint != barycenter_component:
                raise ValueError(
                    f"endpoint_kind {self.endpoint_kind.value!r} does not match "
                    f"orbit component {self.orbit.component.value!r}: a barycenter "
                    "endpoint requires component 'barycenter' and a component "
                    "endpoint requires 'primary' or 'secondary'"
                )
        _require_finite("priority", self.priority)
        if self.priority < 0.0:
            raise ValueError(f"priority must be non-negative, got {self.priority}")
        if self.provider_id == "linear_astrometry_v1":
            unsupported = sorted(UNSUPPORTED_TARGET_FLAGS.intersection(self.flags))
            if unsupported:
                raise ValueError(
                    f"flags {unsupported} mark motion the linear_astrometry_v1 "
                    "family cannot model; select an acceleration or orbital "
                    "provider (registry schema v2) or remove the target"
                )
        provenance_names = [entry.parameter for entry in self.parameter_provenance]
        if len(set(provenance_names)) != len(provenance_names):
            raise ValueError("parameter_provenance entries must be unique per parameter")


@dataclass(frozen=True)
class Observer:
    """A declarative observer spec, resolved to a state-provider family.

    v1 kinds are Earth center and a fixed terrestrial site; roadmap §2.4
    adds Solar-System bodies (from the pinned planetary ephemeris),
    spacecraft from a checksummed tabular ephemeris or a SPICE SPK kernel,
    and a programmatic observer for testing and specialized integrations
    (its state function is registered at runtime via
    :func:`sglseti.providers.register_programmatic_observer`; ``identity``
    is the caller-declared content identity of that function).

    File-backed kinds carry a ``path`` plus a REQUIRED pinned
    ``checksum_sha256``: identities (calculation IDs, manifests) carry the
    resource content checksum, and the canonical rules drop ``path``
    fields, so the identity is complete without touching the file.
    """

    observer_id: str
    kind: ObserverKind
    longitude_deg: float | None = None
    latitude_deg: float | None = None
    height_m: float | None = None
    body: str | None = None
    path: str | None = None
    checksum_sha256: str | None = None
    spice_target: str | None = None
    identity: str | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.observer_id):
            raise ValueError(
                f"observer_id must match {_ID_PATTERN.pattern!r}, got {self.observer_id!r}"
            )
        geodetic = (self.longitude_deg, self.latitude_deg, self.height_m)
        self._require_only(
            {
                ObserverKind.EARTH_CENTER: (),
                ObserverKind.SITE: ("longitude_deg", "latitude_deg", "height_m"),
                ObserverKind.SOLAR_SYSTEM_BODY: ("body",),
                ObserverKind.SPACECRAFT_TABLE: ("path", "checksum_sha256"),
                ObserverKind.SPACECRAFT_SPICE: (
                    "path",
                    "spice_target",
                    "checksum_sha256",
                ),
                ObserverKind.PROGRAMMATIC: ("identity",),
            }[self.kind]
        )
        if self.kind is ObserverKind.EARTH_CENTER:
            if any(value is not None for value in geodetic):
                raise ValueError("an earth_center observer must not define geodetic fields")
            return
        if self.kind is ObserverKind.SITE:
            if any(value is None for value in geodetic):
                raise ValueError("a site observer requires longitude_deg, latitude_deg, height_m")
            assert self.longitude_deg is not None
            assert self.latitude_deg is not None
            assert self.height_m is not None
            _require_finite("longitude_deg", self.longitude_deg)
            _require_finite("latitude_deg", self.latitude_deg)
            _require_finite("height_m", self.height_m)
            if not -180.0 <= self.longitude_deg <= 180.0:
                raise ValueError(
                    f"longitude_deg must be within [-180, 180], got {self.longitude_deg}"
                )
            if not -90.0 <= self.latitude_deg <= 90.0:
                raise ValueError(f"latitude_deg must be within [-90, 90], got {self.latitude_deg}")
            if not -500.0 <= self.height_m <= 10000.0:
                raise ValueError(f"height_m must be within [-500, 10000], got {self.height_m}")
            return
        if self.kind is ObserverKind.SOLAR_SYSTEM_BODY:
            if not self.body or not self.body.strip():
                raise ValueError("a solar_system_body observer requires a body name")
            if self.body != self.body.strip().lower():
                raise ValueError(f"body must be a lowercase ephemeris body name, got {self.body!r}")
            return
        if self.kind in (ObserverKind.SPACECRAFT_TABLE, ObserverKind.SPACECRAFT_SPICE):
            if not self.path or not self.path.strip():
                raise ValueError(f"a {self.kind.value} observer requires a path")
            if self.kind is ObserverKind.SPACECRAFT_SPICE and (
                not self.spice_target or not self.spice_target.strip()
            ):
                raise ValueError(
                    "a spacecraft_spice observer requires a spice_target (NAIF ID or body name)"
                )
            if not self.checksum_sha256 or not self.checksum_sha256.strip():
                raise ValueError(
                    f"a {self.kind.value} observer requires checksum_sha256: "
                    "identities carry the resource CONTENT checksum, never "
                    "the path"
                )
            return
        assert self.kind is ObserverKind.PROGRAMMATIC
        if not self.identity or not self.identity.strip():
            raise ValueError(
                "a programmatic observer requires a caller-declared identity "
                "string (the content identity of its registered state function)"
            )

    def _require_only(self, allowed: tuple[str, ...]) -> None:
        optional = (
            "longitude_deg",
            "latitude_deg",
            "height_m",
            "body",
            "path",
            "checksum_sha256",
            "spice_target",
            "identity",
        )
        offending = [
            name for name in optional if name not in allowed and getattr(self, name) is not None
        ]
        # Geodetic-field violations for earth_center keep their original
        # message (raised by the caller); everything else fails here.
        if self.kind is ObserverKind.EARTH_CENTER:
            offending = [
                name
                for name in offending
                if name not in ("longitude_deg", "latitude_deg", "height_m")
            ]
        if offending:
            raise ValueError(f"a {self.kind.value} observer does not take {sorted(offending)}")

    @classmethod
    def earth_center(cls) -> Observer:
        return cls(observer_id="earth-center", kind=ObserverKind.EARTH_CENTER)

    @classmethod
    def from_geodetic(
        cls,
        name: str,
        longitude: object,
        latitude: object,
        height: object,
    ) -> Observer:
        """Build a site observer from floats (deg/m) or astropy Quantities."""
        return cls(
            observer_id=name,
            kind=ObserverKind.SITE,
            longitude_deg=_quantity_value(longitude, "deg", "longitude"),
            latitude_deg=_quantity_value(latitude, "deg", "latitude"),
            height_m=_quantity_value(height, "m", "height"),
        )

    @classmethod
    def solar_system_body(cls, body: str, observer_id: str | None = None) -> Observer:
        """A Solar-System body observer from the pinned planetary ephemeris."""
        return cls(
            observer_id=observer_id if observer_id is not None else body,
            kind=ObserverKind.SOLAR_SYSTEM_BODY,
            body=body,
        )

    @classmethod
    def spacecraft_table(cls, observer_id: str, path: str, *, checksum_sha256: str) -> Observer:
        """A spacecraft observer from a checksummed tabular ephemeris (ECSV)."""
        return cls(
            observer_id=observer_id,
            kind=ObserverKind.SPACECRAFT_TABLE,
            path=path,
            checksum_sha256=checksum_sha256,
        )

    @classmethod
    def spacecraft_spice(
        cls,
        observer_id: str,
        path: str,
        spice_target: str,
        *,
        checksum_sha256: str,
    ) -> Observer:
        """A spacecraft observer from a SPICE SPK kernel (optional spiceypy)."""
        return cls(
            observer_id=observer_id,
            kind=ObserverKind.SPACECRAFT_SPICE,
            path=path,
            spice_target=spice_target,
            checksum_sha256=checksum_sha256,
        )

    @classmethod
    def programmatic(cls, observer_id: str, identity: str) -> Observer:
        """A programmatic observer; register its state function separately."""
        return cls(observer_id=observer_id, kind=ObserverKind.PROGRAMMATIC, identity=identity)


@dataclass(frozen=True)
class EphemerisSpec:
    """Which Solar-System ephemeris to use and how to identify it.

    ``checksum_sha256`` and ``coverage`` are captured by the ephemeris adapter
    (Phase 4) for file-backed resources; they are ``None`` until then.
    """

    adapter: EphemerisAdapter = EphemerisAdapter.ASTROPY_BUILTIN
    path: str | None = None
    checksum_sha256: str | None = None
    coverage: str | None = None

    def __post_init__(self) -> None:
        if self.adapter is EphemerisAdapter.JPL_FILE and not self.path:
            raise ValueError("ephemeris adapter jpl_file requires a path")
        if self.adapter is EphemerisAdapter.ASTROPY_BUILTIN and self.path is not None:
            raise ValueError("ephemeris adapter astropy_builtin does not take a path")


@dataclass(frozen=True)
class IersSpec:
    """A pinned local IERS-A Earth-orientation table for apparent products.

    The file is installed explicitly for the calculation (astropy's
    ``earth_orientation_table`` context) and identified by content checksum,
    never by path — the same policy as file-backed ephemerides. Without a
    spec, astropy's bundled tables are used and identified by the
    ``astropy-iers-data`` package version. Only apparent (CIRS/AltAz) and
    site-visibility products depend on this resource; geometric ICRS never
    does.
    """

    path: str
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("iers spec requires a path")


@dataclass(frozen=True, init=False)
class RelayRange:
    """Heliocentric relay-distance interval, stored in AU.

    Accepts plain AU floats or astropy Quantities:
    ``RelayRange(550 * u.au, 2500 * u.au)`` or ``RelayRange(550.0, 2500.0)``.
    """

    z_min_au: float
    z_max_au: float

    def __init__(self, z_min: object, z_max: object) -> None:
        object.__setattr__(self, "z_min_au", _quantity_value(z_min, "AU", "z_min"))
        object.__setattr__(self, "z_max_au", _quantity_value(z_max, "AU", "z_max"))
        if self.z_min_au <= 0.0:
            raise ValueError(f"z_min must be positive, got {self.z_min_au} AU")
        if self.z_max_au <= self.z_min_au:
            raise ValueError(f"z_max ({self.z_max_au} AU) must exceed z_min ({self.z_min_au} AU)")


@dataclass(frozen=True)
class SamplingSpec:
    """How to sample a relay range into an ordered corridor.

    Exactly one policy field applies, selected by ``kind``:
    a fixed segment ``count``, a reciprocal-distance angular ``step_arcsec``
    (q = 1/z, approximately the parallax angle for a 1 AU baseline), or an
    ``explicit`` strictly increasing list of distances in AU.
    """

    kind: SamplingKind
    count: int | None = None
    step_arcsec: float | None = None
    distances_au: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        provided = {
            "count": self.count is not None,
            "step_arcsec": self.step_arcsec is not None,
            "distances_au": self.distances_au is not None,
        }
        expected = {
            SamplingKind.COUNT: "count",
            SamplingKind.RECIPROCAL_STEP: "step_arcsec",
            SamplingKind.EXPLICIT: "distances_au",
        }[self.kind]
        for name, given in provided.items():
            if name == expected and not given:
                raise ValueError(f"sampling kind {self.kind} requires {name}")
            if name != expected and given:
                raise ValueError(f"sampling kind {self.kind} does not take {name}")
        if self.count is not None:
            if isinstance(self.count, bool) or self.count < 1 or self.count > 100_000:
                raise ValueError(f"count must be an integer in [1, 100000], got {self.count}")
        if self.step_arcsec is not None:
            _require_finite("step_arcsec", self.step_arcsec)
            if self.step_arcsec <= 0.0:
                raise ValueError(f"step_arcsec must be positive, got {self.step_arcsec}")
        if self.distances_au is not None:
            if not self.distances_au:
                raise ValueError("distances_au must be non-empty")
            for value in self.distances_au:
                _require_finite("distances_au entry", value)
                if value <= 0.0:
                    raise ValueError(f"distances_au entries must be positive, got {value}")
            pairs = zip(self.distances_au, self.distances_au[1:], strict=False)
            if any(b <= a for a, b in pairs):
                raise ValueError("distances_au must be strictly increasing")


@dataclass(frozen=True)
class RangeSegment:
    """One deterministic reciprocal-distance interval of a relay range.

    Identity is physical: it depends on target, role, and the exact distance
    bounds — never on the requested calendar date (PRD §7.7). ``z_rep_au``
    is the reciprocal-midpoint representative distance at which the segment
    is evaluated. Explicit distance samples are zero-width segments
    (``is_point=True``). There are no coverage or completion semantics.
    """

    segment_id: str
    target_id: str
    role: Role
    index: int
    z_near_au: float
    z_far_au: float
    q_lo_per_au: float  # 1 / z_far
    q_hi_per_au: float  # 1 / z_near
    z_rep_au: float
    is_point: bool = False

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.target_id):
            raise ValueError(f"invalid target ID {self.target_id!r}")
        if self.index < 0:
            raise ValueError(f"index must be non-negative, got {self.index}")
        for name, value in (
            ("z_near_au", self.z_near_au),
            ("z_far_au", self.z_far_au),
            ("q_lo_per_au", self.q_lo_per_au),
            ("q_hi_per_au", self.q_hi_per_au),
            ("z_rep_au", self.z_rep_au),
        ):
            _require_finite(name, value)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive, got {value}")
        if self.is_point:
            if not (self.z_near_au == self.z_far_au == self.z_rep_au):
                raise ValueError("a point segment requires z_near == z_far == z_rep")
        else:
            if not self.z_near_au < self.z_far_au:
                raise ValueError(
                    f"z_near_au ({self.z_near_au}) must be below z_far_au ({self.z_far_au})"
                )
            if not self.z_near_au <= self.z_rep_au <= self.z_far_au:
                raise ValueError("z_rep_au must lie within [z_near_au, z_far_au]")
        if self.q_lo_per_au > self.q_hi_per_au:
            raise ValueError("q_lo_per_au must not exceed q_hi_per_au")


@dataclass(frozen=True)
class Epoch:
    """A caller-identified observation time plus pass-through metadata.

    ``time`` is an astropy ``Time`` with UTC scale; ``metadata`` carries
    extra input columns (stringified) so outputs stay joinable to caller
    data. Epochs materialized from an :class:`ObservationInterval` carry
    the interval linkage (``interval_id``, ``interval_phase``,
    ``interval_duration_s``), which flows onto every product row.
    """

    epoch_id: str
    time: Time
    metadata: Mapping[str, str] = field(default_factory=dict)
    interval_id: str | None = None
    interval_phase: str | None = None
    interval_duration_s: float | None = None

    def __post_init__(self) -> None:
        if not _EPOCH_ID_PATTERN.match(self.epoch_id):
            raise ValueError(
                f"epoch_id must be non-empty without whitespace, got {self.epoch_id!r}"
            )
        interval_fields = (self.interval_id, self.interval_phase, self.interval_duration_s)
        if any(value is not None for value in interval_fields) and any(
            value is None for value in interval_fields
        ):
            raise ValueError(
                "interval-linked epochs require all of interval_id, "
                "interval_phase, interval_duration_s"
            )


@dataclass(frozen=True)
class TimeSingle:
    """Time mode 1: one explicit epoch."""

    epoch: Epoch


@dataclass(frozen=True)
class TimeList:
    """Time mode 2: a caller-supplied list with stable epoch IDs."""

    epochs: tuple[Epoch, ...]

    def __post_init__(self) -> None:
        if not self.epochs:
            raise ValueError("epoch list must be non-empty")
        seen: set[str] = set()
        for epoch in self.epochs:
            if epoch.epoch_id in seen:
                raise ValueError(f"duplicate epoch_id {epoch.epoch_id!r}")
            seen.add(epoch.epoch_id)


@dataclass(frozen=True)
class TimeGrid:
    """Time mode 3: start, stop, and cadence in seconds."""

    start: Time
    stop: Time
    cadence_s: float

    def __post_init__(self) -> None:
        _require_finite("cadence_s", self.cadence_s)
        if self.cadence_s <= 0.0:
            raise ValueError(f"cadence_s must be positive, got {self.cadence_s}")
        if not self.start < self.stop:
            raise ValueError("grid start must precede stop")


@dataclass(frozen=True)
class TimeIntervals:
    """Time mode 4: first-class observation intervals (§3.1, §3.5).

    Each interval materializes into epochs at its labeled sample times
    (start/mid/stop, or the declared subintegration grid) with
    deterministic epoch IDs ``<interval_id>@<phase>``; product rows carry
    the interval linkage columns.
    """

    intervals: tuple[ObservationInterval, ...]

    def __post_init__(self) -> None:
        if not self.intervals:
            raise ValueError("interval list must be non-empty")
        seen: set[str] = set()
        for interval in self.intervals:
            if interval.interval_id in seen:
                raise ValueError(f"duplicate interval_id {interval.interval_id!r}")
            seen.add(interval.interval_id)


TimeSpec = TimeSingle | TimeList | TimeGrid | TimeIntervals


@dataclass(frozen=True)
class ObservationInterval:
    """A first-class archival observation interval (roadmap §3.1).

    Represents one observation as a continuous span rather than an
    instantaneous midpoint: start, stop, derived midpoint and duration, an
    optional subintegration cadence, and pass-through metadata (stringified
    caller columns, as on :class:`Epoch`). ``interval_id`` is the join key
    carried onto interval products. Point epochs remain fully supported —
    short exposures can keep using :class:`Epoch` at the midpoint.
    """

    interval_id: str
    start: Time
    stop: Time
    subintegration_cadence_s: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _EPOCH_ID_PATTERN.match(self.interval_id):
            raise ValueError(
                f"interval_id must be non-empty without whitespace, got {self.interval_id!r}"
            )
        if not self.start < self.stop:
            raise ValueError("observation interval start must precede stop")
        if self.subintegration_cadence_s is not None:
            _require_finite("subintegration_cadence_s", self.subintegration_cadence_s)
            if self.subintegration_cadence_s <= 0.0:
                raise ValueError(
                    "subintegration_cadence_s must be positive, "
                    f"got {self.subintegration_cadence_s}"
                )
            if self.subintegration_cadence_s > self.duration_s:
                raise ValueError(
                    f"subintegration_cadence_s ({self.subintegration_cadence_s}) "
                    f"must not exceed the interval duration ({self.duration_s} s)"
                )

    @property
    def duration_s(self) -> float:
        """Exposure/integration duration in seconds."""
        return float((self.stop - self.start).sec)

    @property
    def midpoint(self) -> Time:
        return self.start + 0.5 * (self.stop - self.start)

    def representative_times(self) -> tuple[Time, Time, Time]:
        """The (start, midpoint, stop) triple every interval product uses."""
        return (self.start, self.midpoint, self.stop)

    def sample_times(self) -> tuple[Time, ...]:
        """Evaluation times for interval products.

        Without a subintegration cadence: (start, midpoint, stop). With
        one: the cadence grid from start, plus the stop time when the grid
        does not land on it.
        """
        return tuple(time for _, time in self.labeled_sample_times())

    def labeled_sample_times(self) -> tuple[tuple[str, Time], ...]:
        """Sample times with deterministic phase labels (§3.5).

        Labels join interval products back to their in-interval position:
        ``start``/``mid``/``stop`` for the representative triple, or
        ``sub-NNNN`` for a declared subintegration grid (plus ``stop``
        when the grid does not land on it).
        """
        if self.subintegration_cadence_s is None:
            start, midpoint, stop = self.representative_times()
            return (("start", start), ("mid", midpoint), ("stop", stop))
        span = self.stop - self.start
        duration = self.duration_s
        steps = int(duration // self.subintegration_cadence_s)
        labeled = [
            (
                f"sub-{k:04d}",
                self.start + span * (k * self.subintegration_cadence_s / duration),
            )
            for k in range(steps + 1)
        ]
        if steps * self.subintegration_cadence_s < duration - 1e-9:
            labeled.append(("stop", self.stop))
        return tuple(labeled)


@dataclass(frozen=True)
class TimeInterval:
    """A caller-identified continuous time span to scan for beam crossings.

    Unlike the point-epoch time modes, an interval is searched continuously:
    the scanner chooses its own evaluation times inside it. ``interval_id``
    is the join key carried onto every crossing event found within the span.
    """

    interval_id: str
    start: Time
    stop: Time

    def __post_init__(self) -> None:
        if not _EPOCH_ID_PATTERN.match(self.interval_id):
            raise ValueError(
                f"interval_id must be non-empty without whitespace, got {self.interval_id!r}"
            )
        if not self.start < self.stop:
            raise ValueError("interval start must precede stop")


@dataclass(frozen=True)
class ObservabilityConstraints:
    """Simple pass/fail thresholds for terrestrial-site planning."""

    min_target_altitude_deg: float
    max_sun_altitude_deg: float
    min_moon_separation_deg: float

    def __post_init__(self) -> None:
        _require_finite("min_target_altitude_deg", self.min_target_altitude_deg)
        _require_finite("max_sun_altitude_deg", self.max_sun_altitude_deg)
        _require_finite("min_moon_separation_deg", self.min_moon_separation_deg)
        if not -90.0 <= self.min_target_altitude_deg <= 90.0:
            raise ValueError("min_target_altitude_deg must be within [-90, 90]")
        if not -90.0 <= self.max_sun_altitude_deg <= 90.0:
            raise ValueError("max_sun_altitude_deg must be within [-90, 90]")
        if not 0.0 <= self.min_moon_separation_deg <= 180.0:
            raise ValueError("min_moon_separation_deg must be within [0, 180]")


@dataclass(frozen=True)
class FieldOfView:
    """Circular usable field of view for pointing grouping (v1: circles only).

    ``exposure_s``, when given, enables half-exposure motion padding on
    pointings (requires rates in the calculation products).
    """

    radius_arcsec: float
    exposure_s: float | None = None

    def __post_init__(self) -> None:
        _require_finite("radius_arcsec", self.radius_arcsec)
        if self.radius_arcsec <= 0.0:
            raise ValueError(f"radius_arcsec must be positive, got {self.radius_arcsec}")
        if self.exposure_s is not None:
            _require_finite("exposure_s", self.exposure_s)
            if self.exposure_s <= 0.0:
                raise ValueError(f"exposure_s must be positive, got {self.exposure_s}")


@dataclass(frozen=True)
class GeometryRequest:
    """A validated calculation request (schema v1).

    Targets are referenced by ID; resolution against a
    :class:`~sglseti.targets.TargetRegistry` happens at generation time so a
    request can be validated without loading astrometry.
    """

    target_ids: tuple[str, ...]
    roles: tuple[Role, ...]
    time: TimeSpec
    observer: Observer
    relay_range: RelayRange
    sampling: SamplingSpec
    model_id: str
    model_parameters: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    ephemeris: EphemerisSpec = field(default_factory=EphemerisSpec)
    iers: IersSpec | None = None
    coordinate_products: tuple[CoordinateProduct, ...] = (CoordinateProduct.ICRS,)
    include_rates: bool = False
    output_formats: tuple[OutputFormat, ...] = (OutputFormat.ECSV, OutputFormat.JSON)
    assumed_half_width_arcsec: float | None = None
    observability: ObservabilityConstraints | None = None
    fov: FieldOfView | None = None

    def __post_init__(self) -> None:
        if not self.target_ids:
            raise ValueError("at least one target ID is required")
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("target IDs must be unique")
        for target_id in self.target_ids:
            if not _ID_PATTERN.match(target_id):
                raise ValueError(f"invalid target ID {target_id!r}")
        if not self.roles:
            raise ValueError("at least one role is required")
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("roles must be unique")
        if self.model_id not in SUPPORTED_MODEL_IDS:
            raise ValueError(
                f"unknown model ID {self.model_id!r}; supported: {sorted(SUPPORTED_MODEL_IDS)}"
            )
        if not self.coordinate_products:
            raise ValueError("at least one coordinate product is required")
        if CoordinateProduct.ICRS not in self.coordinate_products:
            raise ValueError("coordinate products must include the canonical 'icrs'")
        if len(set(self.coordinate_products)) != len(self.coordinate_products):
            raise ValueError("coordinate products must be unique")
        if not self.output_formats:
            raise ValueError("at least one output format is required")
        if len(set(self.output_formats)) != len(self.output_formats):
            raise ValueError("output formats must be unique")
        site_only: list[str] = []
        if CoordinateProduct.ALTAZ in self.coordinate_products:
            site_only.append("altaz coordinates")
        if self.observability is not None:
            site_only.append("observability constraints")
        if site_only and self.observer.kind is not ObserverKind.SITE:
            raise ValueError(f"{' and '.join(site_only)} require a terrestrial site observer")
        if self.assumed_half_width_arcsec is not None:
            _require_finite("assumed_half_width_arcsec", self.assumed_half_width_arcsec)
            if self.assumed_half_width_arcsec <= 0.0:
                raise ValueError("assumed_half_width_arcsec must be positive")
        if self.fov is not None and self.fov.exposure_s is not None and not self.include_rates:
            raise ValueError("fov.exposure_s (motion padding) requires products.rates: true")
        if OutputFormat.DS9 in self.output_formats and self.assumed_half_width_arcsec is None:
            raise ValueError(
                "ds9 region output requires an explicit "
                "uncertainty.assumed_half_width_arcsec: regions carry a width, "
                "and an unlabeled width would masquerade as propagated "
                "uncertainty (ADR-0001)"
            )
        if self.sampling.kind is SamplingKind.EXPLICIT:
            assert self.sampling.distances_au is not None
            low, high = self.relay_range.z_min_au, self.relay_range.z_max_au
            for value in self.sampling.distances_au:
                if not low <= value <= high:
                    raise ValueError(
                        f"explicit distance {value} AU is outside the relay range "
                        f"[{low}, {high}] AU"
                    )


#: Coarse scan cadence bounds in days. The impact-parameter history of a
#: one-AU observer has at most semiannual structure, so minima are bracketed
#: reliably for any step comfortably below ~90 days; 30 days is a
#: conservative ceiling and the floor only guards against runaway scans.
CROSSING_SCAN_STEP_MIN_DAYS = 0.01
CROSSING_SCAN_STEP_MAX_DAYS = 30.0


@dataclass(frozen=True)
class CrossingsRequest:
    """A validated beam-crossing search request (crossings schema v1).

    Targets are referenced by ID and resolved against a
    :class:`~sglseti.targets.TargetRegistry` at search time, mirroring
    :class:`GeometryRequest`. ``relay_distance_au`` is the single
    representative relay distance of the hypothesis: the crossing axis does
    not depend on it, but validity checks and the relay pointing product do.

    ``beam_radii_au`` are caller-assumed effective beam radii at the
    observer — hypothesis parameters, never physical claims; each produces
    ingress/egress windows on events whose minimum impact parameter is
    inside it. ``report_max_b_au`` optionally suppresses events whose
    minimum impact parameter exceeds it; by default every local minimum is
    reported (the impact parameter itself is the product; detectability is
    the consumer's judgment).
    """

    target_ids: tuple[str, ...]
    link_directions: tuple[LinkDirection, ...]
    intervals: tuple[TimeInterval, ...]
    observer: Observer
    relay_distance_au: float
    model_id: str
    beam_radii_au: tuple[float, ...] = ()
    report_max_b_au: float | None = None
    coarse_step_days: float = 10.0
    refine_tolerance_s: float = 60.0
    ephemeris: EphemerisSpec = field(default_factory=EphemerisSpec)
    output_formats: tuple[OutputFormat, ...] = (OutputFormat.ECSV, OutputFormat.JSON)

    def __post_init__(self) -> None:
        if not self.target_ids:
            raise ValueError("at least one target ID is required")
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("target IDs must be unique")
        for target_id in self.target_ids:
            if not _ID_PATTERN.match(target_id):
                raise ValueError(f"invalid target ID {target_id!r}")
        if not self.link_directions:
            raise ValueError("at least one link direction is required")
        if len(set(self.link_directions)) != len(self.link_directions):
            raise ValueError("link directions must be unique")
        if not self.intervals:
            raise ValueError("at least one time interval is required")
        interval_ids = [interval.interval_id for interval in self.intervals]
        if len(set(interval_ids)) != len(interval_ids):
            raise ValueError("interval IDs must be unique")
        _require_finite("relay_distance_au", self.relay_distance_au)
        if self.relay_distance_au <= 0.0:
            raise ValueError(f"relay_distance_au must be positive, got {self.relay_distance_au}")
        if self.model_id not in SUPPORTED_MODEL_IDS:
            raise ValueError(
                f"unknown model ID {self.model_id!r}; supported: {sorted(SUPPORTED_MODEL_IDS)}"
            )
        for value in self.beam_radii_au:
            _require_finite("beam_radii_au entry", value)
            if value <= 0.0:
                raise ValueError(f"beam_radii_au entries must be positive, got {value}")
        pairs = zip(self.beam_radii_au, self.beam_radii_au[1:], strict=False)
        if any(b <= a for a, b in pairs):
            raise ValueError("beam_radii_au must be strictly increasing")
        if self.report_max_b_au is not None:
            _require_finite("report_max_b_au", self.report_max_b_au)
            if self.report_max_b_au <= 0.0:
                raise ValueError("report_max_b_au must be positive")
        _require_finite("coarse_step_days", self.coarse_step_days)
        if not (
            CROSSING_SCAN_STEP_MIN_DAYS <= self.coarse_step_days <= CROSSING_SCAN_STEP_MAX_DAYS
        ):
            raise ValueError(
                "coarse_step_days must be within "
                f"[{CROSSING_SCAN_STEP_MIN_DAYS}, {CROSSING_SCAN_STEP_MAX_DAYS}], "
                f"got {self.coarse_step_days}"
            )
        _require_finite("refine_tolerance_s", self.refine_tolerance_s)
        if not 0.0 < self.refine_tolerance_s <= 3600.0:
            raise ValueError(
                f"refine_tolerance_s must be within (0, 3600], got {self.refine_tolerance_s}"
            )
        if not self.output_formats:
            raise ValueError("at least one output format is required")
        if len(set(self.output_formats)) != len(self.output_formats):
            raise ValueError("output formats must be unique")
        if OutputFormat.DS9 in self.output_formats:
            raise ValueError(
                "crossing products are tabular event/window records; DS9 "
                "regions are a locus/pointing product of geometry requests"
            )


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectionSolution:
    """One role's propagated target direction with full epoch diagnostics.

    The intermediate scientific result of a geometry model, per the frozen
    Phase 0 contract in ``docs/science/geometry_models.md`` §4. The catalog
    direction epoch is an SSB light-arrival epoch (Gaia/ERFA convention);
    the physical target-event epoch is a separate diagnostic and is never an
    input to catalog propagation in ``tusay2022_eq5_7_v1``.
    """

    model_id: str
    model_version: str
    role: Role
    observation_epoch: Time
    catalog_direction_epoch: Time
    relay_event_epoch_approx: Time
    solar_lens_epoch_approx: Time
    target_event_epoch_approx: Time
    target_event_kind: TargetEventKind
    target_light_time_days: float
    sun_relay_light_time_days: float
    observer_relay_light_time_days_approx: float
    target_direction_icrs_ra_deg: float
    target_direction_icrs_dec_deg: float
    validity: Validity
    warnings: tuple[str, ...] = ()
    catalog_epoch_semantics: str = "ssb_light_arrival_time"
    # Approximation flags: fixed True for tusay2022_eq5_7_v1; present so
    # future models can differ. Not per-sample toggles.
    rho_equals_z_assumed: bool = True
    constant_target_distance_assumed: bool = True
    linear_stellar_motion_assumed: bool = True
    solar_motion_neglected: bool = True


@dataclass(frozen=True)
class LocusSample:
    """One predicted coordinate for a target, role, epoch, and relay range.

    Epoch semantics follow the reconciled ``tusay2022_eq5_7_v1`` convention:
    ``catalog_direction_epoch`` is an SSB light-arrival epoch, distinct from
    the approximate physical ``target_event_epoch``.
    """

    # identity
    calculation_id: str
    epoch_id: str
    target_id: str
    role: Role
    sample_id: str
    # time
    observation_time_utc: str
    observation_time_tdb_jd: float
    catalog_direction_epoch_tdb_jd: float
    relay_event_epoch_tdb_jd_approx: float
    solar_lens_epoch_tdb_jd_approx: float
    target_event_epoch_tdb_jd_approx: float
    target_event_kind: TargetEventKind
    # light times
    target_light_time_days: float
    sun_relay_light_time_days: float
    observer_relay_light_time_days_approx: float
    # range
    z_au: float
    q_per_au: float
    # geometry (canonical geometric ICRS from the stated observer)
    icrs_ra_deg: float
    icrs_dec_deg: float
    observer_id: str
    # model
    model_id: str
    model_version: str
    # provenance (§3.5): the adopted solutions behind this row, by content
    target_source_hash: str
    ephemeris_id: str
    target_provider_id: str
    target_provider_version: str
    target_provider_hash: str
    observer_provider_id: str
    observer_provider_version: str
    observer_provider_hash: str
    # quality
    validity: Validity
    uncertainty_method: UncertaintyMethod
    warnings: tuple[str, ...] = ()
    # observation-interval linkage (None for point epochs)
    interval_id: str | None = None
    interval_phase: str | None = None
    interval_duration_s: float | None = None
    # fixed epoch semantics and approximation flags for this model family
    catalog_epoch_semantics: str = "ssb_light_arrival_time"
    rho_equals_z_assumed: bool = True
    solar_motion_neglected: bool = True
    linear_stellar_motion_assumed: bool = True
    constant_target_distance_assumed: bool = True
    # optional apparent products
    cirs_ra_deg: float | None = None
    cirs_dec_deg: float | None = None
    altaz_alt_deg: float | None = None
    altaz_az_deg: float | None = None
    # optional motion
    rate_ra_cosdec_arcsec_per_hr: float | None = None
    rate_dec_arcsec_per_hr: float | None = None
    # represented relay-distance interval (segment bounds; near == far for
    # explicit point segments)
    z_near_au: float | None = None
    z_far_au: float | None = None
    q_lo_per_au: float | None = None
    q_hi_per_au: float | None = None
    # geometric ICRS at the interval boundaries — the coverage extremes a
    # pointing footprint must contain, not just the representative point
    near_icrs_ra_deg: float | None = None
    near_icrs_dec_deg: float | None = None
    far_icrs_ra_deg: float | None = None
    far_icrs_dec_deg: float | None = None
    # motion rates at the near boundary, the interval's fastest point
    near_rate_ra_cosdec_arcsec_per_hr: float | None = None
    near_rate_dec_arcsec_per_hr: float | None = None

    def coverage_radec(self) -> tuple[tuple[float, float], ...]:
        """Sky points a footprint must contain to cover this sample.

        The representative coordinate plus any finite interval-boundary
        coordinates. Samples without boundary data degrade to the
        representative point alone.
        """
        points = [(self.icrs_ra_deg, self.icrs_dec_deg)]
        for ra, dec in (
            (self.near_icrs_ra_deg, self.near_icrs_dec_deg),
            (self.far_icrs_ra_deg, self.far_icrs_dec_deg),
        ):
            if ra is not None and dec is not None and math.isfinite(ra) and math.isfinite(dec):
                points.append((ra, dec))
        return tuple(points)

    @property
    def is_operational(self) -> bool:
        """Whether this sample may enter observing products.

        Invalid samples can still carry finite coordinates (e.g. the
        ``z > d/10`` model bound) as diagnostics; ``validity`` is the
        authoritative gate, finiteness only a backstop.
        """
        return self.validity is not Validity.INVALID and math.isfinite(self.icrs_ra_deg)


@dataclass(frozen=True)
class Corridor:
    """Ordered locus samples across a relay range at one target/role/epoch."""

    corridor_id: str
    calculation_id: str
    target_id: str
    role: Role
    epoch_id: str
    samples: tuple[LocusSample, ...]
    z_min_au: float
    z_max_au: float
    uncertainty_method: UncertaintyMethod
    assumed_half_width_arcsec: float | None = None
    max_motion_padding_arcsec: float | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocusPoint:
    """One continuous-locus evaluation: geometric ICRS direction at (t, z).

    The scalar product of the public continuous mapping
    ``(target, role, observation time, observer, z) -> direction``
    (roadmap §3.2). ``validity`` and ``warnings`` carry the underlying
    direction solution's quality verbatim.
    """

    z_au: float
    q_per_au: float
    icrs_ra_deg: float
    icrs_dec_deg: float
    validity: Validity
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_finite("z_au", self.z_au)
        if self.z_au <= 0.0:
            raise ValueError(f"z_au must be positive, got {self.z_au}")
        _require_finite("q_per_au", self.q_per_au)


@dataclass(frozen=True)
class AdaptiveLocus:
    """An ordered locus polyline with a guaranteed angular fidelity bound.

    Produced by the adaptive sampler (roadmap §3.2): every point of the
    continuous locus over ``[z_min_au, z_max_au]`` lies within
    ``tolerance_arcsec`` of this polyline (subject to the sampler's declared
    smoothness assumption and to ``warnings`` — a budget warning means the
    bound could not be guaranteed). ``achieved_deviation_arcsec`` is the
    largest deviation measured at the sampler's probe points of accepted
    segments; the guaranteed polyline bound is ``tolerance_arcsec`` (probes
    are accepted at half that). Points are ordered by ascending ``z_au``
    and retain the mapping back to ``z``; the first and last points are the
    relay-range boundary coordinates.
    """

    target_id: str
    role: Role
    observation_time: Time
    observer_id: str
    z_min_au: float
    z_max_au: float
    tolerance_arcsec: float
    achieved_deviation_arcsec: float
    points: tuple[LocusPoint, ...]
    model_id: str
    model_version: str
    ephemeris_id: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("an adaptive locus requires at least two points")
        _require_finite("tolerance_arcsec", self.tolerance_arcsec)
        if self.tolerance_arcsec <= 0.0:
            raise ValueError("tolerance_arcsec must be positive")
        _require_finite("achieved_deviation_arcsec", self.achieved_deviation_arcsec)
        pairs = zip(self.points, self.points[1:], strict=False)
        if any(b.z_au <= a.z_au for a, b in pairs):
            raise ValueError("adaptive locus points must be strictly increasing in z")
        if self.points[0].z_au != self.z_min_au or self.points[-1].z_au != self.z_max_au:
            raise ValueError("adaptive locus endpoints must sit at z_min_au and z_max_au")

    @property
    def boundary_points(self) -> tuple[LocusPoint, LocusPoint]:
        """The relay-range boundary coordinates (z_min and z_max points)."""
        return (self.points[0], self.points[-1])


@dataclass(frozen=True)
class SweptLocus:
    """A conservative swept locus over one observation interval.

    Ordered instantaneous polylines at adaptively chosen times such that
    the locus midway between adjacent times stays within
    ``time_tolerance_arcsec`` of them. Every instantaneous locus point in
    the interval lies within ``envelope_pad_arcsec`` of the union of the
    returned polylines (= time tolerance + per-polyline z tolerance), under
    the sampler's declared smooth-drift assumption and subject to
    ``warnings``.
    """

    interval_id: str
    target_id: str
    role: Role
    observer_id: str
    loci: tuple[AdaptiveLocus, ...]
    tolerance_arcsec: float
    time_tolerance_arcsec: float
    envelope_pad_arcsec: float
    model_id: str
    model_version: str
    ephemeris_id: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.loci) < 2:
            raise ValueError("a swept locus requires at least the two boundary times")
        for name, value in (
            ("tolerance_arcsec", self.tolerance_arcsec),
            ("time_tolerance_arcsec", self.time_tolerance_arcsec),
            ("envelope_pad_arcsec", self.envelope_pad_arcsec),
        ):
            _require_finite(name, value)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive, got {value}")


@dataclass(frozen=True)
class ZInterval:
    """A covered relay-distance interval refined from a caller's footprint.

    Endpoints are the inside-most refined bracket points, so both are
    verified covered; the true boundary lies within the refinement
    tolerance outside them.
    """

    z_min_au: float
    z_max_au: float

    def __post_init__(self) -> None:
        _require_finite("z_min_au", self.z_min_au)
        _require_finite("z_max_au", self.z_max_au)
        if self.z_min_au <= 0.0:
            raise ValueError(f"z_min_au must be positive, got {self.z_min_au}")
        if self.z_max_au < self.z_min_au:
            raise ValueError("z_max_au must not be below z_min_au")


@dataclass(frozen=True)
class IntervalState:
    """Target position and motion at one representative interval time."""

    interval_id: str
    time_utc: str
    z_au: float
    icrs_ra_deg: float
    icrs_dec_deg: float
    rate_ra_cosdec_arcsec_per_hr: float
    rate_dec_arcsec_per_hr: float
    validity: Validity
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisibilitySample:
    """Site-dependent observing context at one grid time.

    ``warnings`` carries Earth-orientation degradation (captured astropy
    transform warnings, IERS coverage): degraded samples still pass or fail
    constraints normally — altitude margins are degree-scale against
    sub-arcsecond EOP errors — but the degradation is never silent.
    """

    target_id: str
    role: Role
    epoch_id: str
    time_utc: str
    altitude_deg: float
    azimuth_deg: float
    sun_altitude_deg: float
    moon_separation_deg: float
    constraints_passed: bool
    failed_constraints: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pointing:
    """A conservative circular candidate zone over adjacent relay segments.

    Pointings are unscheduled candidate zones, never a scheduled sequence.
    ``radius_arcsec`` is the conservative total; its components are kept
    separate so an assumed width is never mistaken for propagated
    covariance: ``radius = track_extent + (assumed or propagated half
    width) + motion_padding + window_drift``, where ``window_drift`` is the
    additional extent the grouped samples sweep across the advertised
    window's grid epochs beyond the representative-epoch track.
    """

    pointing_id: str
    calculation_id: str
    target_id: str
    role: Role
    sample_ids: tuple[str, ...]
    center_icrs_ra_deg: float
    center_icrs_dec_deg: float
    radius_arcsec: float
    usable_radius_arcsec: float
    representative_time_utc: str
    window_start_utc: str | None = None
    window_stop_utc: str | None = None
    warnings: tuple[str, ...] = ()
    # Conservative-radius components (plan §Phase 6 task 5):
    track_extent_arcsec: float = 0.0
    assumed_half_width_arcsec: float | None = None
    propagated_half_width_arcsec: float | None = None  # v1: never set
    motion_padding_arcsec: float = 0.0
    # relay-distance interval this pointing claims to cover (first grouped
    # sample's near bound through the last's far bound)
    z_near_au: float | None = None
    z_far_au: float | None = None
    # positional drift envelope across the advertised window (grid-sampled)
    window_drift_arcsec: float = 0.0


@dataclass(frozen=True)
class CalculationResult:
    """Immutable calculation output plus provenance and warnings.

    ``iers_id`` is the resolved Earth-orientation resource identity —
    ``iers_a:sha256:…`` for a pinned table, ``iers_bundled:…`` for astropy's
    bundled data — recorded only when the request has apparent or
    site-visibility products, which are the outputs that depend on it.
    """

    calculation_id: str
    request: GeometryRequest
    samples: tuple[LocusSample, ...] = ()
    corridors: tuple[Corridor, ...] = ()
    visibility: tuple[VisibilitySample, ...] = ()
    pointings: tuple[Pointing, ...] = ()
    warnings: tuple[str, ...] = ()
    iers_id: str | None = None


@dataclass(frozen=True)
class ImpactSample:
    """The beam-axis impact parameter of an observer at one instant.

    The scalar product of the crossing axis model (ADR-0003): the
    perpendicular distance ``b`` of the observer from the Sun-anchored beam
    axis, with the signed along-axis distance and side. The impact parameter
    is reported as-is — whether it constitutes a "crossing" depends on the
    consumer's beam hypothesis.
    """

    target_id: str
    link_direction: LinkDirection
    observer_id: str
    time_utc: str
    time_tdb_jd: float
    b_au: float
    b_km: float
    b_solar_radii: float
    axis_distance_au: float
    side: BeamSide
    axis_icrs_ra_deg: float
    axis_icrs_dec_deg: float
    role: Role
    z_au: float
    axis_model_id: str
    axis_model_version: str
    model_id: str
    model_version: str
    validity: Validity
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeamWindow:
    """One assumed-beam-radius ingress/egress window around a crossing event.

    ``beam_radius_au`` is the caller's assumed effective beam radius at the
    observer — a hypothesis parameter, never a propagated physical width. A
    truncated boundary means the impact parameter was still inside the
    radius at the requested interval's edge, so the true boundary lies
    outside the searched span.
    """

    window_id: str
    event_id: str
    beam_radius_au: float
    ingress_utc: str
    egress_utc: str
    ingress_tdb_jd: float
    egress_tdb_jd: float
    duration_days: float
    truncated_ingress: bool = False
    truncated_egress: bool = False


@dataclass(frozen=True)
class CrossingEvent:
    """One local minimum of the observer's beam-axis impact parameter.

    ``axis_icrs_*`` is the barycentric catalog axis direction at closest
    approach; ``star_icrs_*`` and ``relay_icrs_*`` are geometric
    observer-relative lines of sight to the propagated target and to the
    hypothesized relay at ``z_au`` — the two pointings an observation of
    the crossing would use (inbound: the star; outbound: the relay locus).
    """

    # identity
    crossings_id: str
    event_id: str
    target_id: str
    link_direction: LinkDirection
    interval_id: str
    minimum_index: int
    observer_id: str
    # time
    t_ca_utc: str
    t_ca_tdb_jd: float
    catalog_direction_epoch_tdb_jd: float
    # geometry
    b_min_au: float
    b_min_km: float
    b_min_solar_radii: float
    axis_distance_au: float
    v_perp_km_s: float
    axis_icrs_ra_deg: float
    axis_icrs_dec_deg: float
    star_icrs_ra_deg: float
    star_icrs_dec_deg: float
    relay_icrs_ra_deg: float
    relay_icrs_dec_deg: float
    z_au: float
    target_light_time_days: float
    # model
    role: Role
    axis_model_id: str
    axis_model_version: str
    model_id: str
    model_version: str
    # provenance (§3.5): the adopted solutions behind this event, by content
    target_source_hash: str
    ephemeris_id: str
    target_provider_id: str
    target_provider_version: str
    target_provider_hash: str
    observer_provider_id: str
    observer_provider_version: str
    observer_provider_hash: str
    # quality
    validity: Validity
    uncertainty_method: UncertaintyMethod
    # ``None`` only on invalid status rows, whose geometry is NaN and whose
    # side is therefore genuinely unknown — never a fabricated label.
    side: BeamSide | None = None
    warnings: tuple[str, ...] = ()
    windows: tuple[BeamWindow, ...] = ()


@dataclass(frozen=True)
class CrossingsResult:
    """Immutable crossing-search output plus provenance and warnings.

    Event order is the documented product order: targets (request order) x
    link directions (request order) x intervals (request order) x minima
    (ascending time).
    """

    crossings_id: str
    request: CrossingsRequest
    events: tuple[CrossingEvent, ...] = ()
    warnings: tuple[str, ...] = ()
