"""Release-gate tests (plan §9): reproducibility and boundary.

- Reproducibility gate: a network-disabled run with pinned resources (the
  checksummed kernel excerpt), repeated from a different working directory,
  reproduces identical science IDs and byte-identical science products.
- Boundary gate: no observation-ledger, historical-coverage, ingest,
  candidate, or SQLite implementation exists under ``sglseti/``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from support import EXAMPLES_DIR

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "sglseti"
KERNEL = Path(__file__).resolve().parents[1] / "data" / "kernels" / (
    "de440s_excerpt_2010-2035.bsp"
)

_NETWORK_BLOCK = """
import sys

def _hook(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.bind") or (
        event.startswith("urllib")
    ):
        raise RuntimeError(f"network access attempted: {event} {args!r}")

sys.addaudithook(_hook)
"""


def _pinned_request(tmp_path: Path) -> Path:
    request = tmp_path / "request.yaml"
    request.write_text(
        f"""
schema_version: 1
targets: [barnard]
roles: [rx, tx]
time:
  epochs:
    - {{epoch_id: r1, time_utc: "2012-06-01T05:30:00Z"}}
    - {{epoch_id: r2, time_utc: "2024-01-20T11:00:00Z"}}
observer:
  kind: site
  name: example-kitt-peak
  longitude_deg: -111.6003
  latitude_deg: 31.9583
  height_m: 2096.0
relay_range:
  min_au: 550.0
  max_au: 2500.0
  sampling: {{kind: count, count: 5}}
model:
  id: tusay2022_eq5_7_v1
ephemeris:
  adapter: jpl_file
  path: {KERNEL}
products:
  coordinates: [icrs]
  formats: [ecsv, json]
""",
        encoding="utf-8",
    )
    return request


def _offline_generate(cwd: Path, request: Path, output_dir: Path) -> None:
    probe = (
        _NETWORK_BLOCK
        + f"""
from sglseti.cli import main
code = main([
    "generate",
    "--targets", {str(EXAMPLES_DIR / "targets.yaml")!r},
    "--request", {str(request)!r},
    "--output-dir", {str(output_dir)!r},
])
assert code == 0, code
"""
    )
    cwd.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_offline_rerun_reproduces_science_ids_and_rows(tmp_path: Path) -> None:
    request = _pinned_request(tmp_path)
    first_out, second_out = tmp_path / "out-a", tmp_path / "out-b"
    _offline_generate(tmp_path / "cwd-a", request, first_out)
    _offline_generate(tmp_path / "cwd-b" / "nested", request, second_out)

    for name in ("samples.ecsv", "corridors.ecsv", "result.json"):
        assert (first_out / name).read_bytes() == (second_out / name).read_bytes()
    first = json.loads((first_out / "result.json").read_text(encoding="utf-8"))
    second = json.loads((second_out / "result.json").read_text(encoding="utf-8"))
    assert first["calculation_id"] == second["calculation_id"]
    assert all(s["validity"] == "valid" for s in first["samples"])
    # Pinned resource identity, not location.
    ephemeris_ids = {s["ephemeris_id"] for s in first["samples"]}
    assert len(ephemeris_ids) == 1
    assert next(iter(ephemeris_ids)).startswith("jpl_file:sha256:")
    manifest_a = json.loads((first_out / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((second_out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_a["science_input_hash"] == manifest_b["science_input_hash"]


def test_boundary_no_ledger_coverage_or_sqlite_implementation() -> None:
    module_names = sorted(p.stem for p in PACKAGE_DIR.glob("*.py"))
    forbidden_modules = {"ledger", "coverage", "ingest", "candidates", "db", "database"}
    assert not forbidden_modules & set(module_names)

    # Importing every sglseti module never pulls in sqlite3 or dbm.
    probe = (
        "import importlib, sys\n"
        f"modules = {module_names!r}\n"
        "for name in modules:\n"
        "    importlib.import_module(f'sglseti.{name}')\n"
        "for forbidden in ('sqlite3', 'dbm'):\n"
        "    assert forbidden not in sys.modules, forbidden\n"
    )
    subprocess.run([sys.executable, "-c", probe], check=True)

    # No SQL or ledger identifiers in package *code* (docstrings and
    # comments may legitimately disclaim these concepts).
    import io
    import tokenize

    for path in PACKAGE_DIR.glob("*.py"):
        code_tokens = " ".join(
            token.string.lower()
            for token in tokenize.generate_tokens(
                io.StringIO(path.read_text(encoding="utf-8")).readline
            )
            if token.type not in (tokenize.COMMENT, tokenize.STRING)
        )
        for forbidden in ("sqlite", "ledger", "observation_record", "cursor"):
            assert forbidden not in code_tokens, f"{forbidden!r} in {path.name}"
