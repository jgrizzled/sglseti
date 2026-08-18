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
    "AstrometricState",
    "CalculationResult",
    "CoordinateProduct",
    "CorrectionType",
    "Corridor",
    "DirectionSolution",
    "EndpointKind",
    "Epoch",
    "EphemerisAdapter",
    "EphemerisSpec",
    "FieldOfView",
    "GeometryRequest",
    "LocusSample",
    "ObservabilityConstraints",
    "Observer",
    "ObserverKind",
    "OutputFormat",
    "Pointing",
    "RelayRange",
    "Role",
    "SamplingKind",
    "SamplingSpec",
    "Target",
    "TargetEventKind",
    "TimeGrid",
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

#: Registry flags the v1 linear-motion baseline cannot model. Their presence
#: is a validation error rather than a silently degraded result.
UNSUPPORTED_TARGET_FLAGS = frozenset({"unresolved_binary", "accelerating_system"})

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_EPOCH_ID_PATTERN = re.compile(r"^\S+$")


class Role(StrEnum):
    ANTIPODE = "antipode"
    RX = "rx"
    TX = "tx"


class EndpointKind(StrEnum):
    STAR = "star"
    COMPONENT = "component"
    BARYCENTER = "barycenter"
    OTHER = "other"


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


@dataclass(frozen=True)
class Target:
    """A curated stellar-system endpoint with validated astrometry."""

    target_id: str
    display_name: str
    endpoint_kind: EndpointKind
    astrometry: AstrometricState
    priority: float = 1.0
    tags: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.target_id):
            raise ValueError(
                f"target_id must match {_ID_PATTERN.pattern!r}, got {self.target_id!r}"
            )
        if not self.display_name:
            raise ValueError("display_name must be non-empty")
        if self.endpoint_kind is EndpointKind.OTHER:
            raise ValueError(
                "endpoint_kind 'other' is not supported by the v1 linear-motion baseline"
            )
        _require_finite("priority", self.priority)
        if self.priority < 0.0:
            raise ValueError(f"priority must be non-negative, got {self.priority}")
        unsupported = sorted(UNSUPPORTED_TARGET_FLAGS.intersection(self.flags))
        if unsupported:
            raise ValueError(
                f"flags {unsupported} mark motion the v1 linear-motion baseline "
                "cannot model; remove the target or use a future orbital model"
            )


@dataclass(frozen=True)
class Observer:
    """Earth center or a fixed terrestrial site with a stable ID."""

    observer_id: str
    kind: ObserverKind
    longitude_deg: float | None = None
    latitude_deg: float | None = None
    height_m: float | None = None

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.observer_id):
            raise ValueError(
                f"observer_id must match {_ID_PATTERN.pattern!r}, got {self.observer_id!r}"
            )
        geodetic = (self.longitude_deg, self.latitude_deg, self.height_m)
        if self.kind is ObserverKind.EARTH_CENTER:
            if any(value is not None for value in geodetic):
                raise ValueError("an earth_center observer must not define geodetic fields")
            return
        if any(value is None for value in geodetic):
            raise ValueError("a site observer requires longitude_deg, latitude_deg, height_m")
        assert self.longitude_deg is not None
        assert self.latitude_deg is not None
        assert self.height_m is not None
        _require_finite("longitude_deg", self.longitude_deg)
        _require_finite("latitude_deg", self.latitude_deg)
        _require_finite("height_m", self.height_m)
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError(f"longitude_deg must be within [-180, 180], got {self.longitude_deg}")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError(f"latitude_deg must be within [-90, 90], got {self.latitude_deg}")
        if not -500.0 <= self.height_m <= 10000.0:
            raise ValueError(f"height_m must be within [-500, 10000], got {self.height_m}")

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
            raise ValueError(
                f"z_max ({self.z_max_au} AU) must exceed z_min ({self.z_min_au} AU)"
            )


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
class Epoch:
    """A caller-identified observation time plus pass-through metadata.

    ``time`` is an astropy ``Time`` with UTC scale; ``metadata`` carries
    extra input columns (stringified) so outputs stay joinable to caller data.
    """

    epoch_id: str
    time: Time
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _EPOCH_ID_PATTERN.match(self.epoch_id):
            raise ValueError(
                f"epoch_id must be non-empty without whitespace, got {self.epoch_id!r}"
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


TimeSpec = TimeSingle | TimeList | TimeGrid


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
    """Circular usable field of view for pointing grouping (v1: circles only)."""

    radius_arcsec: float

    def __post_init__(self) -> None:
        _require_finite("radius_arcsec", self.radius_arcsec)
        if self.radius_arcsec <= 0.0:
            raise ValueError(f"radius_arcsec must be positive, got {self.radius_arcsec}")


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
            raise ValueError(
                f"{' and '.join(site_only)} require a terrestrial site observer"
            )
        if self.assumed_half_width_arcsec is not None:
            _require_finite("assumed_half_width_arcsec", self.assumed_half_width_arcsec)
            if self.assumed_half_width_arcsec <= 0.0:
                raise ValueError("assumed_half_width_arcsec must be positive")
        if self.sampling.kind is SamplingKind.EXPLICIT:
            assert self.sampling.distances_au is not None
            low, high = self.relay_range.z_min_au, self.relay_range.z_max_au
            for value in self.sampling.distances_au:
                if not low <= value <= high:
                    raise ValueError(
                        f"explicit distance {value} AU is outside the relay range "
                        f"[{low}, {high}] AU"
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
    # provenance
    target_source_hash: str
    ephemeris_id: str
    # quality
    validity: Validity
    uncertainty_method: UncertaintyMethod
    warnings: tuple[str, ...] = ()
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
class VisibilitySample:
    """Site-dependent observing context at one grid time."""

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


@dataclass(frozen=True)
class Pointing:
    """A conservative circular candidate zone over adjacent relay segments.

    Pointings are unscheduled candidate zones, never a scheduled sequence.
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


@dataclass(frozen=True)
class CalculationResult:
    """Immutable calculation output plus provenance and warnings."""

    calculation_id: str
    request: GeometryRequest
    samples: tuple[LocusSample, ...] = ()
    corridors: tuple[Corridor, ...] = ()
    visibility: tuple[VisibilitySample, ...] = ()
    pointings: tuple[Pointing, ...] = ()
    warnings: tuple[str, ...] = ()
