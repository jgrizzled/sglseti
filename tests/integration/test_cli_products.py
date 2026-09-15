"""End-to-end CLI product tests: generate/plan write what the API writes.

Products are read back with astropy and the stdlib only — consumable without
importing sglseti internals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import EXAMPLES_DIR

from sglseti.cli import main

KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / ("de440s_excerpt_2010-2035.bsp")


def test_generate_cli_matches_direct_api(tmp_path: Path, capsys) -> None:
    cli_dir = tmp_path / "cli"
    code = main(
        [
            "generate",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(EXAMPLES_DIR / "historical.yaml"),
            "--output-dir",
            str(cli_dir),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "samples: 200 (0 invalid)" in output

    # Direct API run with the same inputs.
    from sglseti.config import load_request
    from sglseti.export import write_products
    from sglseti.generate import generate_loci
    from sglseti.targets import load_target_registry

    api_dir = tmp_path / "api"
    result = generate_loci(
        load_request(EXAMPLES_DIR / "historical.yaml"),
        load_target_registry(EXAMPLES_DIR / "targets.yaml"),
    )
    write_products(result, api_dir, generated_utc="2026-08-17T00:00:00+00:00")

    # Science products are byte-identical; manifests share the science hash.
    for name in ("samples.ecsv", "corridors.ecsv", "result.json"):
        assert (cli_dir / name).read_bytes() == (api_dir / name).read_bytes()
    cli_manifest = json.loads((cli_dir / "manifest.json").read_text(encoding="utf-8"))
    api_manifest = json.loads((api_dir / "manifest.json").read_text(encoding="utf-8"))
    # The CLI adds input-file hashes (part of science identity); everything
    # else about the science block matches.
    assert (
        cli_manifest["science_inputs"]["calculation_id"]
        == api_manifest["science_inputs"]["calculation_id"]
    )
    assert cli_manifest["science_inputs"]["request"] == (api_manifest["science_inputs"]["request"])
    assert set(cli_manifest["science_inputs"]["input_file_hashes"]) == {
        "targets_yaml",
        "request_yaml",
    }


def test_products_consumable_with_stdlib_and_astropy_only(tmp_path: Path) -> None:
    code = main(
        [
            "generate",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(EXAMPLES_DIR / "historical.yaml"),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    from astropy.table import Table

    table = Table.read(tmp_path / "samples.ecsv", format="ascii.ecsv")
    document = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    # Join back to the input epoch table without loss.
    input_ids = {
        "archive-exposure-1",
        "archive-exposure-2",
        "archive-exposure-3",
        "archive-exposure-4",
    }
    assert set(str(v) for v in table["epoch_id"]) == input_ids
    assert {s["epoch_id"] for s in document["samples"]} == input_ids


def test_generate_epochs_override(tmp_path: Path, capsys) -> None:
    epochs = tmp_path / "override.csv"
    epochs.write_text("epoch_id,time_utc\ncustom-1,2020-05-05T05:00:00Z\n", encoding="utf-8")
    code = main(
        [
            "generate",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(EXAMPLES_DIR / "historical.yaml"),
            "--epochs",
            str(epochs),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert "samples: 50 (0 invalid)" in capsys.readouterr().out  # 2 roles x 25
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert "epochs_table" in manifest["science_inputs"]["input_file_hashes"]


@pytest.mark.filterwarnings("ignore:ERFA function.*dubious year")
def test_generate_exit_1_on_invalid_rows(tmp_path: Path, capsys) -> None:
    request = tmp_path / "request.yaml"
    request.write_text(
        f"""
schema_version: 1
targets: [barnard]
roles: [rx]
time:
  epoch_utc: "2036-06-01T00:00:00Z"   # outside the excerpt kernel coverage
observer:
  kind: earth_center
relay_range:
  min_au: 550.0
  max_au: 2500.0
  sampling: {{kind: count, count: 2}}
model:
  id: tusay2022_eq5_7_v1
ephemeris:
  adapter: jpl_file
  path: {KERNEL}
""",
        encoding="utf-8",
    )
    code = main(
        [
            "generate",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(request),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 1  # completed, but with invalid status rows
    captured = capsys.readouterr()
    assert "samples: 2 (2 invalid)" in captured.out
    assert "invalid_sample_count:2" in captured.err
    # Products were still written, with explicit invalid rows.
    document = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert all(s["validity"] == "invalid" for s in document["samples"])

    # Strict mode refuses instead.
    strict_code = main(
        [
            "generate",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(request),
            "--output-dir",
            str(tmp_path / "strict"),
            "--strict",
        ]
    )
    assert strict_code == 2
    assert "strict mode" in capsys.readouterr().err


def test_plan_cli_small_night(tmp_path: Path, capsys) -> None:
    request = tmp_path / "night.yaml"
    request.write_text(
        """
schema_version: 1
targets: [barnard]
roles: [rx]
time:
  grid:
    start_utc: "2021-11-06T06:00:00Z"
    stop_utc: "2021-11-06T08:00:00Z"
    cadence_s: 3600.0
observer:
  kind: site
  name: example-kitt-peak
  longitude_deg: -111.6003
  latitude_deg: 31.9583
  height_m: 2096.0
relay_range:
  min_au: 550.0
  max_au: 2500.0
  sampling: {kind: count, count: 3}
model:
  id: tusay2022_eq5_7_v1
products:
  coordinates: [icrs]
  rates: true
  formats: [ecsv, json, ds9]
uncertainty:
  assumed_half_width_arcsec: 30.0
observability:
  min_target_altitude_deg: 25.0
  max_sun_altitude_deg: -12.0
  min_moon_separation_deg: 20.0
fov:
  radius_arcsec: 300.0
  exposure_s: 300.0
""",
        encoding="utf-8",
    )
    code = main(
        [
            "plan",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(request),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "visibility: 3" in output
    assert (tmp_path / "out" / "visibility.ecsv").is_file()
    assert (tmp_path / "out" / "manifest.json").is_file()
    document = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert len(document["visibility"]) == 3
    if document["pointings"]:
        assert (tmp_path / "out" / "pointings.ecsv").is_file()


def test_plan_cli_requires_planning_blocks(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "plan",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(EXAMPLES_DIR / "historical.yaml"),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert "observability" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["generate", "plan"])
def test_missing_input_file_exits_2(tmp_path: Path, command: str, capsys) -> None:
    code = main(
        [
            command,
            "--targets",
            "/nonexistent/targets.yaml",
            "--request",
            str(EXAMPLES_DIR / "historical.yaml"),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert "error: " in capsys.readouterr().err
