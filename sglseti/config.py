"""YAML/ECSV/CSV parsing and validation for sglseti inputs.

Every validation failure raises :class:`~sglseti.errors.ConfigError` with a
message of the form ``<file>: <dotted.path>: <problem>`` so users can locate
the offending value directly.

Astropy imports are function-local on purpose: validation-only commands
(``validate``, ``samples``) should not pay for heavy scientific imports.
Geometry modules import astropy normally.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import yaml

from .errors import ConfigError
from .models import (
    SUPPORTED_MODEL_IDS,
    CoordinateProduct,
    EphemerisAdapter,
    EphemerisSpec,
    Epoch,
    FieldOfView,
    GeometryRequest,
    ObservabilityConstraints,
    Observer,
    ObserverKind,
    OutputFormat,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    TimeGrid,
    TimeList,
    TimeSingle,
    TimeSpec,
)

if TYPE_CHECKING:
    from astropy.time import Time

__all__ = [
    "REQUEST_SCHEMA_VERSION",
    "load_epoch_table",
    "load_request",
    "load_yaml",
]

REQUEST_SCHEMA_VERSION = 1

#: Upper bound on materialized epochs from a grid; prevents accidental
#: million-row requests from a typo'd cadence.
MAX_GRID_EPOCHS = 1_000_000

_Fail = Callable[[str, str], NoReturn]


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last."""


def _construct_mapping_strict(
    loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate mapping key {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_strict
)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file whose top level must be a mapping.

    Duplicate mapping keys anywhere in the document are an error.
    """
    path = Path(path)
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except FileNotFoundError as exc:
        raise ConfigError(f"file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def _fail_factory(path: Path) -> _Fail:
    def _fail(ctx: str, message: str) -> NoReturn:
        raise ConfigError(f"{path}: {ctx}: {message}")

    return _fail


def _check_keys(raw: dict[str, Any], allowed: set[str], ctx: str, fail: _Fail) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        fail(ctx, f"unknown key(s) {unknown}; allowed: {sorted(allowed)}")


def _mapping(raw: Any, ctx: str, fail: _Fail) -> dict[str, Any]:
    if not isinstance(raw, dict):
        fail(ctx, "must be a mapping")
    return raw


def _string(raw: dict[str, Any], key: str, ctx: str, fail: _Fail) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{ctx}.{key}", "must be a non-empty string")
    return value.strip()


def _number(raw: dict[str, Any], key: str, ctx: str, fail: _Fail) -> float:
    value = raw.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{ctx}.{key}", f"must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        fail(f"{ctx}.{key}", f"must be finite, got {value!r}")
    return number


def _integer(raw: dict[str, Any], key: str, ctx: str, fail: _Fail) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{ctx}.{key}", f"must be an integer, got {value!r}")
    return value


def _string_list(raw: Any, ctx: str, fail: _Fail) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        fail(ctx, "must be a list of strings")
    return tuple(item.strip() for item in raw)


def _build(ctx: str, fail: _Fail, factory: Callable[..., Any], /, **kwargs: Any) -> Any:
    """Construct a domain object, converting its ValueError into a ConfigError."""
    try:
        return factory(**kwargs)
    except ValueError as exc:
        fail(ctx, str(exc))


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def _parse_utc(value: Any, ctx: str, fail: _Fail) -> Time:
    """Parse an ISO-8601 timestamp with a mandatory UTC designator or offset.

    Naive timestamps are rejected: sglseti never guesses a timezone. YAML may
    hand us a ``datetime`` directly (unquoted timestamps); the same rule
    applies to it.
    """
    from astropy.time import Time

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            fail(ctx, f"invalid ISO-8601 timestamp {value!r}")
    else:
        fail(ctx, f"must be an ISO-8601 UTC timestamp string, got {value!r}")
    if parsed.tzinfo is None:
        fail(
            ctx,
            f"timestamp {value!r} has no UTC designator or offset; "
            "use e.g. 2021-11-06T03:14:00Z",
        )
    naive_utc = parsed.astimezone(UTC).replace(tzinfo=None)
    return Time(naive_utc, scale="utc", format="datetime")


# ---------------------------------------------------------------------------
# Batch epoch tables (ECSV canonical, CSV convenience)
# ---------------------------------------------------------------------------

_REQUIRED_EPOCH_COLUMNS = ("epoch_id", "time_utc")


def load_epoch_table(path: str | Path) -> tuple[Epoch, ...]:
    """Load a batch epoch table with stable ``epoch_id`` join keys.

    ECSV (by extension ``.ecsv``) is the lossless input form; CSV is accepted
    as a convenience. Required columns: ``epoch_id`` and ``time_utc`` (ISO
    UTC with designator/offset; naive timestamps are rejected). Additional
    columns are carried through as stringified per-epoch metadata.
    """
    path = Path(path)
    fail = _fail_factory(path)
    if not path.is_file():
        raise ConfigError(f"file not found: {path}")
    if path.suffix.lower() == ".ecsv":
        rows, columns = _read_ecsv_rows(path)
    elif path.suffix.lower() == ".csv":
        rows, columns = _read_csv_rows(path)
    else:
        raise ConfigError(
            f"{path}: unsupported epoch table format {path.suffix!r}; use .ecsv or .csv"
        )
    missing = [column for column in _REQUIRED_EPOCH_COLUMNS if column not in columns]
    if missing:
        fail("columns", f"missing required column(s) {missing}")
    if not rows:
        fail("rows", "epoch table has no rows")
    extra_columns = [column for column in columns if column not in _REQUIRED_EPOCH_COLUMNS]
    epochs: list[Epoch] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        ctx = f"row {index + 1}"
        epoch_id = str(row.get("epoch_id", "")).strip()
        if not epoch_id:
            fail(f"{ctx}.epoch_id", "must be non-empty")
        if epoch_id in seen:
            fail(f"{ctx}.epoch_id", f"duplicate epoch_id {epoch_id!r}")
        seen.add(epoch_id)
        time = _parse_utc(row.get("time_utc"), f"{ctx}.time_utc", fail)
        metadata = {column: str(row[column]) for column in extra_columns}
        epochs.append(
            _build(ctx, fail, Epoch, epoch_id=epoch_id, time=time, metadata=metadata)
        )
    return tuple(epochs)


def _read_ecsv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    # Local import: astropy.table is heavy and only needed for ECSV input.
    from astropy.table import Table

    try:
        table = Table.read(path, format="ascii.ecsv")
    except Exception as exc:
        raise ConfigError(f"{path}: invalid ECSV: {exc}") from exc
    columns = list(table.colnames)
    rows = [{column: row[column] for column in columns} for row in table]
    return rows, columns


def _read_csv_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ConfigError(f"{path}: CSV file has no header row")
        columns = [name.strip() for name in reader.fieldnames]
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append({(k or "").strip(): (v if v is not None else "") for k, v in row.items()})
    return rows, columns


# ---------------------------------------------------------------------------
# Calculation request (schema v1)
# ---------------------------------------------------------------------------

_TOP_KEYS = {
    "schema_version",
    "targets",
    "roles",
    "time",
    "observer",
    "relay_range",
    "model",
    "ephemeris",
    "products",
    "uncertainty",
    "observability",
    "fov",
}

_TIME_MODE_KEYS = ("epoch_utc", "epochs", "epochs_file", "grid")


def load_request(path: str | Path) -> GeometryRequest:
    """Load and strictly validate a calculation request YAML file.

    An ``epochs_file`` reference is resolved relative to the request file's
    directory and its table is loaded and validated as part of this call.
    Target IDs are validated structurally only; existence in a registry is
    checked at generation time.
    """
    path = Path(path)
    fail = _fail_factory(path)
    data = load_yaml(path)
    if data.get("schema_version") != REQUEST_SCHEMA_VERSION:
        fail("schema_version", f"must be {REQUEST_SCHEMA_VERSION}")
    _check_keys(data, _TOP_KEYS, "request", fail)

    target_ids = _string_list(data.get("targets"), "targets", fail)
    roles = _parse_roles(data.get("roles"), fail)
    time_spec = _parse_time(data.get("time"), path.parent, fail)
    observer = _parse_observer(data.get("observer"), fail)
    relay_range, sampling = _parse_relay_range(data.get("relay_range"), fail)
    model_id, model_parameters = _parse_model(data.get("model"), fail)
    ephemeris = _parse_ephemeris(data.get("ephemeris"), fail)
    coordinate_products, include_rates, output_formats = _parse_products(
        data.get("products"), fail
    )
    assumed_half_width = _parse_uncertainty(data.get("uncertainty"), fail)
    observability = _parse_observability(data.get("observability"), fail)
    fov = _parse_fov(data.get("fov"), fail)

    request: GeometryRequest = _build(
        "request",
        fail,
        GeometryRequest,
        target_ids=target_ids,
        roles=roles,
        time=time_spec,
        observer=observer,
        relay_range=relay_range,
        sampling=sampling,
        model_id=model_id,
        model_parameters=model_parameters,
        ephemeris=ephemeris,
        coordinate_products=coordinate_products,
        include_rates=include_rates,
        output_formats=output_formats,
        assumed_half_width_arcsec=assumed_half_width,
        observability=observability,
        fov=fov,
    )
    return request


def _parse_roles(raw: Any, fail: _Fail) -> tuple[Role, ...]:
    names = _string_list(raw, "roles", fail)
    if not names:
        fail("roles", "must list at least one role")
    roles: list[Role] = []
    for name in names:
        try:
            roles.append(Role(name))
        except ValueError:
            fail("roles", f"unknown role {name!r}; choose from {[r.value for r in Role]}")
    return tuple(roles)


def _parse_time(raw: Any, base_dir: Path, fail: _Fail) -> TimeSpec:
    block = _mapping(raw, "time", fail)
    present = [key for key in _TIME_MODE_KEYS if key in block]
    if len(present) != 1:
        fail(
            "time",
            f"exactly one time mode of {list(_TIME_MODE_KEYS)} is required, got {present}",
        )
    _check_keys(block, {present[0], "epoch_id"}, "time", fail)
    mode = present[0]
    if mode == "epoch_utc":
        epoch_id = str(block.get("epoch_id", "epoch-0")).strip()
        time = _parse_utc(block["epoch_utc"], "time.epoch_utc", fail)
        epoch: Epoch = _build("time", fail, Epoch, epoch_id=epoch_id, time=time)
        return TimeSingle(epoch=epoch)
    if "epoch_id" in block:
        fail("time.epoch_id", f"only valid with epoch_utc, not {mode}")
    if mode == "epochs":
        return TimeList(epochs=_parse_inline_epochs(block["epochs"], fail))
    if mode == "epochs_file":
        file_value = block["epochs_file"]
        if not isinstance(file_value, str) or not file_value.strip():
            fail("time.epochs_file", "must be a non-empty path string")
        epochs_path = Path(file_value)
        if not epochs_path.is_absolute():
            epochs_path = base_dir / epochs_path
        return TimeList(epochs=load_epoch_table(epochs_path))
    grid = _mapping(block["grid"], "time.grid", fail)
    _check_keys(grid, {"start_utc", "stop_utc", "cadence_s"}, "time.grid", fail)
    start = _parse_utc(grid.get("start_utc"), "time.grid.start_utc", fail)
    stop = _parse_utc(grid.get("stop_utc"), "time.grid.stop_utc", fail)
    cadence_s = _number(grid, "cadence_s", "time.grid", fail)
    spec: TimeGrid = _build(
        "time.grid", fail, TimeGrid, start=start, stop=stop, cadence_s=cadence_s
    )
    epoch_count = math.floor(float((spec.stop - spec.start).sec) / spec.cadence_s) + 1
    if epoch_count > MAX_GRID_EPOCHS:
        fail(
            "time.grid",
            f"grid would produce {epoch_count} epochs; limit is {MAX_GRID_EPOCHS}",
        )
    return spec


def _parse_inline_epochs(raw: Any, fail: _Fail) -> tuple[Epoch, ...]:
    if not isinstance(raw, list) or not raw:
        fail("time.epochs", "must be a non-empty list of epoch mappings")
    epochs: list[Epoch] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        ctx = f"time.epochs[{index}]"
        entry = _mapping(item, ctx, fail)
        epoch_id = _string(entry, "epoch_id", ctx, fail)
        if epoch_id in seen:
            fail(f"{ctx}.epoch_id", f"duplicate epoch_id {epoch_id!r}")
        seen.add(epoch_id)
        if "time_utc" not in entry:
            fail(ctx, "missing required key time_utc")
        time = _parse_utc(entry["time_utc"], f"{ctx}.time_utc", fail)
        metadata = {
            key: str(value)
            for key, value in entry.items()
            if key not in {"epoch_id", "time_utc"}
        }
        epochs.append(
            _build(ctx, fail, Epoch, epoch_id=epoch_id, time=time, metadata=metadata)
        )
    return tuple(epochs)


def _parse_observer(raw: Any, fail: _Fail) -> Observer:
    block = _mapping(raw, "observer", fail)
    kind_name = _string(block, "kind", "observer", fail)
    try:
        kind = ObserverKind(kind_name)
    except ValueError:
        fail("observer.kind", f"must be one of {[k.value for k in ObserverKind]}")
    if kind is ObserverKind.EARTH_CENTER:
        _check_keys(block, {"kind"}, "observer", fail)
        return Observer.earth_center()
    _check_keys(
        block, {"kind", "name", "longitude_deg", "latitude_deg", "height_m"}, "observer", fail
    )
    observer: Observer = _build(
        "observer",
        fail,
        Observer,
        observer_id=_string(block, "name", "observer", fail),
        kind=ObserverKind.SITE,
        longitude_deg=_number(block, "longitude_deg", "observer", fail),
        latitude_deg=_number(block, "latitude_deg", "observer", fail),
        height_m=_number(block, "height_m", "observer", fail),
    )
    return observer


def _parse_relay_range(raw: Any, fail: _Fail) -> tuple[RelayRange, SamplingSpec]:
    block = _mapping(raw, "relay_range", fail)
    _check_keys(block, {"min_au", "max_au", "sampling"}, "relay_range", fail)
    relay_range: RelayRange = _build(
        "relay_range",
        fail,
        RelayRange,
        z_min=_number(block, "min_au", "relay_range", fail),
        z_max=_number(block, "max_au", "relay_range", fail),
    )
    sampling_block = _mapping(block.get("sampling"), "relay_range.sampling", fail)
    kind_name = _string(sampling_block, "kind", "relay_range.sampling", fail)
    try:
        kind = SamplingKind(kind_name)
    except ValueError:
        fail(
            "relay_range.sampling.kind",
            f"must be one of {[k.value for k in SamplingKind]}",
        )
    allowed = {"kind"}
    kwargs: dict[str, Any] = {"kind": kind}
    if kind is SamplingKind.COUNT:
        allowed.add("count")
        kwargs["count"] = _integer(sampling_block, "count", "relay_range.sampling", fail)
    elif kind is SamplingKind.RECIPROCAL_STEP:
        allowed.add("step_arcsec")
        kwargs["step_arcsec"] = _number(
            sampling_block, "step_arcsec", "relay_range.sampling", fail
        )
    else:
        allowed.add("distances_au")
        distances = sampling_block.get("distances_au")
        if not isinstance(distances, list) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in distances
        ):
            fail("relay_range.sampling.distances_au", "must be a list of numbers")
        kwargs["distances_au"] = tuple(float(v) for v in distances)
    _check_keys(sampling_block, allowed, "relay_range.sampling", fail)
    sampling: SamplingSpec = _build("relay_range.sampling", fail, SamplingSpec, **kwargs)
    return relay_range, sampling


def _parse_model(raw: Any, fail: _Fail) -> tuple[str, dict[str, str | int | float | bool]]:
    block = _mapping(raw, "model", fail)
    _check_keys(block, {"id", "parameters"}, "model", fail)
    model_id = _string(block, "id", "model", fail)
    if model_id not in SUPPORTED_MODEL_IDS:
        fail("model.id", f"unknown model {model_id!r}; supported: {sorted(SUPPORTED_MODEL_IDS)}")
    parameters_raw = block.get("parameters", {})
    parameters = _mapping(parameters_raw, "model.parameters", fail) if parameters_raw else {}
    for key, value in parameters.items():
        if not isinstance(key, str):
            fail("model.parameters", f"parameter names must be strings, got {key!r}")
        if isinstance(value, (dict, list)) or value is None:
            fail(f"model.parameters.{key}", "must be a scalar (string, number, or boolean)")
    return model_id, dict(parameters)


def _parse_ephemeris(raw: Any, fail: _Fail) -> EphemerisSpec:
    if raw is None:
        return EphemerisSpec()
    block = _mapping(raw, "ephemeris", fail)
    adapter_name = _string(block, "adapter", "ephemeris", fail)
    try:
        adapter = EphemerisAdapter(adapter_name)
    except ValueError:
        fail("ephemeris.adapter", f"must be one of {[a.value for a in EphemerisAdapter]}")
    spec: EphemerisSpec
    if adapter is EphemerisAdapter.JPL_FILE:
        _check_keys(block, {"adapter", "path"}, "ephemeris", fail)
        spec = _build(
            "ephemeris",
            fail,
            EphemerisSpec,
            adapter=adapter,
            path=_string(block, "path", "ephemeris", fail),
        )
    else:
        _check_keys(block, {"adapter"}, "ephemeris", fail)
        spec = _build("ephemeris", fail, EphemerisSpec, adapter=adapter)
    return spec


def _parse_products(
    raw: Any, fail: _Fail
) -> tuple[tuple[CoordinateProduct, ...], bool, tuple[OutputFormat, ...]]:
    if raw is None:
        return (CoordinateProduct.ICRS,), False, (OutputFormat.ECSV, OutputFormat.JSON)
    block = _mapping(raw, "products", fail)
    _check_keys(block, {"coordinates", "rates", "formats"}, "products", fail)
    coordinates: tuple[CoordinateProduct, ...] = (CoordinateProduct.ICRS,)
    if "coordinates" in block:
        names = _string_list(block["coordinates"], "products.coordinates", fail)
        parsed: list[CoordinateProduct] = []
        for name in names:
            try:
                parsed.append(CoordinateProduct(name))
            except ValueError:
                fail(
                    "products.coordinates",
                    f"unknown product {name!r}; choose from "
                    f"{[c.value for c in CoordinateProduct]}",
                )
        coordinates = tuple(parsed)
    rates = block.get("rates", False)
    if not isinstance(rates, bool):
        fail("products.rates", f"must be a boolean, got {rates!r}")
    formats: tuple[OutputFormat, ...] = (OutputFormat.ECSV, OutputFormat.JSON)
    if "formats" in block:
        names = _string_list(block["formats"], "products.formats", fail)
        parsed_formats: list[OutputFormat] = []
        for name in names:
            try:
                parsed_formats.append(OutputFormat(name))
            except ValueError:
                fail(
                    "products.formats",
                    f"unknown format {name!r}; choose from {[f.value for f in OutputFormat]}",
                )
        formats = tuple(parsed_formats)
    return coordinates, rates, formats


def _parse_uncertainty(raw: Any, fail: _Fail) -> float | None:
    if raw is None:
        return None
    block = _mapping(raw, "uncertainty", fail)
    _check_keys(block, {"assumed_half_width_arcsec"}, "uncertainty", fail)
    return _number(block, "assumed_half_width_arcsec", "uncertainty", fail)


def _parse_observability(raw: Any, fail: _Fail) -> ObservabilityConstraints | None:
    if raw is None:
        return None
    block = _mapping(raw, "observability", fail)
    _check_keys(
        block,
        {"min_target_altitude_deg", "max_sun_altitude_deg", "min_moon_separation_deg"},
        "observability",
        fail,
    )
    constraints: ObservabilityConstraints = _build(
        "observability",
        fail,
        ObservabilityConstraints,
        min_target_altitude_deg=_number(
            block, "min_target_altitude_deg", "observability", fail
        ),
        max_sun_altitude_deg=_number(block, "max_sun_altitude_deg", "observability", fail),
        min_moon_separation_deg=_number(
            block, "min_moon_separation_deg", "observability", fail
        ),
    )
    return constraints


def _parse_fov(raw: Any, fail: _Fail) -> FieldOfView | None:
    if raw is None:
        return None
    block = _mapping(raw, "fov", fail)
    _check_keys(block, {"radius_arcsec"}, "fov", fail)
    fov: FieldOfView = _build(
        "fov", fail, FieldOfView, radius_arcsec=_number(block, "radius_arcsec", "fov", fail)
    )
    return fov
