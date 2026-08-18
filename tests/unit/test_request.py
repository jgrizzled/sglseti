from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from sglseti.config import load_request
from sglseti.errors import ConfigError
from sglseti.models import (
    CoordinateProduct,
    EphemerisAdapter,
    ObserverKind,
    OutputFormat,
    Role,
    SamplingKind,
    TimeGrid,
    TimeList,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def base_request() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "targets": ["barnard"],
        "roles": ["rx", "tx"],
        "time": {"epoch_utc": "2021-11-06T03:14:00Z"},
        "observer": {
            "kind": "site",
            "name": "example-site",
            "longitude_deg": -111.6,
            "latitude_deg": 31.96,
            "height_m": 2096.0,
        },
        "relay_range": {
            "min_au": 550.0,
            "max_au": 2500.0,
            "sampling": {"kind": "count", "count": 25},
        },
        "model": {"id": "tusay2022_eq5_7_v1"},
    }


def write_request(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "request.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_historical_example_loads() -> None:
    request = load_request(EXAMPLES / "historical.yaml")
    assert request.target_ids == ("barnard",)
    assert request.roles == (Role.RX, Role.TX)
    assert isinstance(request.time, TimeList)
    assert len(request.time.epochs) == 4
    assert request.time.epochs[0].epoch_id == "archive-exposure-1"
    assert request.time.epochs[2].metadata == {"dataset_id": "GBT-ALPHACEN-DEMO"}
    assert request.observer.kind is ObserverKind.SITE
    assert request.sampling.kind is SamplingKind.COUNT
    assert request.assumed_half_width_arcsec == 30.0
    assert request.ephemeris.adapter is EphemerisAdapter.ASTROPY_BUILTIN


def test_commensal_example_loads() -> None:
    request = load_request(EXAMPLES / "commensal-night.yaml")
    assert isinstance(request.time, TimeGrid)
    assert request.time.cadence_s == 600.0
    assert request.include_rates is True
    assert CoordinateProduct.ALTAZ in request.coordinate_products
    assert request.observability is not None
    assert request.fov is not None
    assert request.fov.radius_arcsec == 204.0
    assert OutputFormat.DS9 in request.output_formats


def test_epoch_offset_normalized_to_utc() -> None:
    request = load_request(EXAMPLES / "historical.yaml")
    assert isinstance(request.time, TimeList)
    fourth = request.time.epochs[3]
    assert fourth.time.isot.startswith("2024-01-20T11:00:00")


def test_minimal_request_defaults(tmp_path: Path) -> None:
    request = load_request(write_request(tmp_path, base_request()))
    assert request.coordinate_products == (CoordinateProduct.ICRS,)
    assert request.include_rates is False
    assert request.output_formats == (OutputFormat.ECSV, OutputFormat.JSON)
    assert request.assumed_half_width_arcsec is None
    assert request.observability is None
    assert request.fov is None


def test_no_time_mode(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {}
    with pytest.raises(ConfigError, match="exactly one time mode"):
        load_request(write_request(tmp_path, data))


def test_two_time_modes(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {
        "epoch_utc": "2021-11-06T03:14:00Z",
        "grid": {
            "start_utc": "2021-11-06T00:00:00Z",
            "stop_utc": "2021-11-07T00:00:00Z",
            "cadence_s": 600,
        },
    }
    with pytest.raises(ConfigError, match="exactly one time mode"):
        load_request(write_request(tmp_path, data))


def test_naive_timestamp_rejected(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {"epoch_utc": "2021-11-06T03:14:00"}
    with pytest.raises(ConfigError, match="no UTC designator or offset"):
        load_request(write_request(tmp_path, data))


def test_unquoted_naive_yaml_timestamp_rejected(tmp_path: Path) -> None:
    # PyYAML parses unquoted ISO timestamps into datetime objects; a naive one
    # must still be rejected rather than assumed UTC.
    data = base_request()
    path = tmp_path / "request.yaml"
    data.pop("time")
    text = yaml.safe_dump(data) + "time:\n  epoch_utc: 2021-11-06 03:14:00\n"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="no UTC designator or offset"):
        load_request(path)


def test_invalid_timestamp(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {"epoch_utc": "yesterday"}
    with pytest.raises(ConfigError, match="invalid ISO-8601"):
        load_request(write_request(tmp_path, data))


def test_grid_stop_before_start(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {
        "grid": {
            "start_utc": "2026-12-15T13:00:00Z",
            "stop_utc": "2026-12-15T01:00:00Z",
            "cadence_s": 600,
        }
    }
    with pytest.raises(ConfigError, match="start must precede stop"):
        load_request(write_request(tmp_path, data))


@pytest.mark.filterwarnings("ignore:ERFA function.*dubious year")
def test_grid_epoch_limit(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {
        "grid": {
            "start_utc": "2000-01-01T00:00:00Z",
            "stop_utc": "2100-01-01T00:00:00Z",
            "cadence_s": 1,
        }
    }
    with pytest.raises(ConfigError, match="limit is"):
        load_request(write_request(tmp_path, data))


def test_unknown_role(tmp_path: Path) -> None:
    data = base_request()
    data["roles"] = ["receiver"]
    with pytest.raises(ConfigError, match="unknown role 'receiver'"):
        load_request(write_request(tmp_path, data))


def test_duplicate_roles(tmp_path: Path) -> None:
    data = base_request()
    data["roles"] = ["rx", "rx"]
    with pytest.raises(ConfigError, match="roles must be unique"):
        load_request(write_request(tmp_path, data))


def test_duplicate_targets(tmp_path: Path) -> None:
    data = base_request()
    data["targets"] = ["barnard", "barnard"]
    with pytest.raises(ConfigError, match="target IDs must be unique"):
        load_request(write_request(tmp_path, data))


def test_unknown_model(tmp_path: Path) -> None:
    data = base_request()
    data["model"] = {"id": "full"}
    with pytest.raises(ConfigError, match="unknown model 'full'"):
        load_request(write_request(tmp_path, data))


def test_unknown_top_level_key(tmp_path: Path) -> None:
    data = base_request()
    data["ledgerr"] = {}
    with pytest.raises(ConfigError, match="unknown key"):
        load_request(write_request(tmp_path, data))


def test_altaz_requires_site(tmp_path: Path) -> None:
    data = base_request()
    data["observer"] = {"kind": "earth_center"}
    data["products"] = {"coordinates": ["icrs", "altaz"]}
    with pytest.raises(ConfigError, match="require a terrestrial site observer"):
        load_request(write_request(tmp_path, data))


def test_observability_requires_site(tmp_path: Path) -> None:
    data = base_request()
    data["observer"] = {"kind": "earth_center"}
    data["observability"] = {
        "min_target_altitude_deg": 25,
        "max_sun_altitude_deg": -12,
        "min_moon_separation_deg": 20,
    }
    with pytest.raises(ConfigError, match="require a terrestrial site observer"):
        load_request(write_request(tmp_path, data))


def test_icrs_product_required(tmp_path: Path) -> None:
    data = base_request()
    data["products"] = {"coordinates": ["cirs"]}
    with pytest.raises(ConfigError, match="must include the canonical 'icrs'"):
        load_request(write_request(tmp_path, data))


def test_earth_center_observer(tmp_path: Path) -> None:
    data = base_request()
    data["observer"] = {"kind": "earth_center"}
    request = load_request(write_request(tmp_path, data))
    assert request.observer.kind is ObserverKind.EARTH_CENTER
    assert request.observer.longitude_deg is None


def test_site_bounds(tmp_path: Path) -> None:
    data = base_request()
    data["observer"]["latitude_deg"] = 95.0
    with pytest.raises(ConfigError, match=r"latitude_deg must be within \[-90, 90\]"):
        load_request(write_request(tmp_path, data))


def test_relay_range_ordering(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["min_au"] = 2500.0
    data["relay_range"]["max_au"] = 550.0
    with pytest.raises(ConfigError, match="must exceed"):
        load_request(write_request(tmp_path, data))


def test_sampling_count_missing(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["sampling"] = {"kind": "count"}
    with pytest.raises(ConfigError, match=r"sampling\.count"):
        load_request(write_request(tmp_path, data))


def test_sampling_explicit_not_increasing(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["sampling"] = {
        "kind": "explicit",
        "distances_au": [600.0, 550.0],
    }
    with pytest.raises(ConfigError, match="strictly increasing"):
        load_request(write_request(tmp_path, data))


def test_sampling_explicit_outside_range(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["sampling"] = {
        "kind": "explicit",
        "distances_au": [500.0, 600.0],
    }
    with pytest.raises(ConfigError, match="outside the relay range"):
        load_request(write_request(tmp_path, data))


def test_sampling_mixed_policy_keys(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["sampling"] = {"kind": "count", "count": 5, "step_arcsec": 15}
    with pytest.raises(ConfigError, match="unknown key"):
        load_request(write_request(tmp_path, data))


def test_ephemeris_jpl_file_requires_path(tmp_path: Path) -> None:
    data = base_request()
    data["ephemeris"] = {"adapter": "jpl_file"}
    with pytest.raises(ConfigError, match=r"ephemeris\.path"):
        load_request(write_request(tmp_path, data))


def test_inline_epochs_with_metadata(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {
        "epochs": [
            {"epoch_id": "a", "time_utc": "2020-01-01T00:00:00Z", "note": "first"},
            {"epoch_id": "b", "time_utc": "2020-01-02T00:00:00Z"},
        ]
    }
    request = load_request(write_request(tmp_path, data))
    assert isinstance(request.time, TimeList)
    assert request.time.epochs[0].metadata == {"note": "first"}


def test_inline_epochs_duplicate_ids(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {
        "epochs": [
            {"epoch_id": "a", "time_utc": "2020-01-01T00:00:00Z"},
            {"epoch_id": "a", "time_utc": "2020-01-02T00:00:00Z"},
        ]
    }
    with pytest.raises(ConfigError, match="duplicate epoch_id"):
        load_request(write_request(tmp_path, data))


def test_missing_epochs_file(tmp_path: Path) -> None:
    data = base_request()
    data["time"] = {"epochs_file": "does-not-exist.ecsv"}
    with pytest.raises(ConfigError, match="file not found"):
        load_request(write_request(tmp_path, data))


def test_error_messages_include_file_and_path(tmp_path: Path) -> None:
    data = base_request()
    data["relay_range"]["min_au"] = "wide"
    path = write_request(tmp_path, data)
    with pytest.raises(ConfigError) as excinfo:
        load_request(path)
    message = str(excinfo.value)
    assert str(path) in message
    assert "relay_range.min_au" in message
