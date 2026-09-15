"""Strict validation of crossings request YAML files."""

from __future__ import annotations

from pathlib import Path

import pytest

from sglseti.config import load_crossings_request
from sglseti.errors import ConfigError
from sglseti.models import LinkDirection, ObserverKind, OutputFormat

VALID = """\
schema_version: 1
targets: [barnard]
link_directions: [inbound, outbound]
intervals:
  - interval_id: archive-era
    start_utc: 1998-01-01T00:00:00Z
    stop_utc: 2003-01-01T00:00:00Z
observer:
  kind: earth_center
relay_distance_au: 800.0
beam:
  radii_au: [0.05, 0.5]
  report_max_b_au: 0.6
scan:
  coarse_step_days: 5.0
  refine_tolerance_s: 30.0
model:
  id: tusay2022_eq5_7_v1
products:
  formats: [ecsv, json, csv]
"""


def write_request(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "crossings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_request_round_trip(tmp_path: Path) -> None:
    request = load_crossings_request(write_request(tmp_path, VALID))
    assert request.target_ids == ("barnard",)
    assert request.link_directions == (
        LinkDirection.INBOUND,
        LinkDirection.OUTBOUND,
    )
    (interval,) = request.intervals
    assert interval.interval_id == "archive-era"
    assert str(interval.start.utc.isot).startswith("1998-01-01")
    assert request.observer.kind is ObserverKind.EARTH_CENTER
    assert request.relay_distance_au == 800.0
    assert request.beam_radii_au == (0.05, 0.5)
    assert request.report_max_b_au == 0.6
    assert request.coarse_step_days == 5.0
    assert request.refine_tolerance_s == 30.0
    assert request.output_formats == (
        OutputFormat.ECSV,
        OutputFormat.JSON,
        OutputFormat.CSV,
    )


def test_defaults_without_optional_blocks(tmp_path: Path) -> None:
    optional = (
        "beam",
        "scan",
        "products",
        "  radii",
        "  report",
        "  coarse",
        "  refine",
        "  formats",
    )
    text = "\n".join(line for line in VALID.splitlines() if not line.startswith(optional))
    request = load_crossings_request(write_request(tmp_path, text))
    assert request.beam_radii_au == ()
    assert request.report_max_b_au is None
    assert request.coarse_step_days == 10.0
    assert request.refine_tolerance_s == 60.0
    assert request.output_formats == (OutputFormat.ECSV, OutputFormat.JSON)


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        ("schema_version: 1", "schema_version: 2", "schema_version"),
        (
            "link_directions: [inbound, outbound]",
            "link_directions: [sideways]",
            "unknown direction",
        ),
        (
            "link_directions: [inbound, outbound]",
            "link_directions: [inbound, inbound]",
            "link directions must be unique",
        ),
        (
            "    stop_utc: 2003-01-01T00:00:00Z",
            "    stop_utc: 1997-01-01T00:00:00Z",
            "start must precede stop",
        ),
        (
            "    stop_utc: 2003-01-01T00:00:00Z",
            "    stop_utc: 2003-01-01T00:00:00",
            "no UTC designator",
        ),
        ("relay_distance_au: 800.0", "relay_distance_au: -1.0", "must be positive"),
        ("  radii_au: [0.05, 0.5]", "  radii_au: [0.5, 0.05]", "strictly increasing"),
        ("  coarse_step_days: 5.0", "  coarse_step_days: 90.0", "coarse_step_days"),
        ("  refine_tolerance_s: 30.0", "  refine_tolerance_s: 0.0", "refine_tolerance_s"),
        ("  id: tusay2022_eq5_7_v1", "  id: mystery_model", "unknown model"),
        ("  formats: [ecsv, json, csv]", "  formats: [ds9]", "tabular"),
        ("targets: [barnard]", "targets: []", "at least one target"),
    ],
)
def test_invalid_values_rejected(
    tmp_path: Path, original: str, replacement: str, message: str
) -> None:
    assert original in VALID
    with pytest.raises(ConfigError, match=message):
        load_crossings_request(write_request(tmp_path, VALID.replace(original, replacement)))


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        load_crossings_request(write_request(tmp_path, VALID + "roles: [rx]\n"))


def test_duplicate_interval_id_rejected(tmp_path: Path) -> None:
    duplicated = VALID.replace(
        "observer:",
        "  - interval_id: archive-era\n"
        "    start_utc: 2010-01-01T00:00:00Z\n"
        "    stop_utc: 2011-01-01T00:00:00Z\n"
        "observer:",
    )
    with pytest.raises(ConfigError, match="duplicate interval_id"):
        load_crossings_request(write_request(tmp_path, duplicated))


def test_model_parameters_rejected(tmp_path: Path) -> None:
    # The crossing axis contract has no model parameters in v1; a
    # parameters block must fail loudly instead of being ignored.
    text = VALID.replace(
        "  id: tusay2022_eq5_7_v1",
        "  id: tusay2022_eq5_7_v1\n  parameters: {foo: 1}",
    )
    with pytest.raises(ConfigError, match="unknown key"):
        load_crossings_request(write_request(tmp_path, text))
