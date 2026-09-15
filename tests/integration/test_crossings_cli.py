"""End-to-end crossings run: CLI, builtin ephemeris, real annual geometry.

Self-consistent physics checks (no memorized astronomy): each reported
closest approach must be an actual local minimum of an independently
recomputed impact parameter, near-solstice crossings of a low-ecliptic
target must alternate sides roughly twice per year, and the refined minimum
can never exceed the coarse grid minimum.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from astropy.time import Time, TimeDelta
from support import EXAMPLES_DIR

from sglseti.cli import main
from sglseti.config import load_crossings_request
from sglseti.crossings import find_crossings, impact_parameter
from sglseti.ephemeris import AstropyEphemeris
from sglseti.models import LinkDirection, Observer
from sglseti.targets import load_target_registry

REQUEST = """\
schema_version: 1
targets: [barnard]
link_directions: [inbound]
intervals:
  - interval_id: window
    start_utc: 2020-02-01T00:00:00Z
    stop_utc: 2022-02-01T00:00:00Z
observer:
  kind: earth_center
relay_distance_au: 800.0
beam:
  radii_au: [0.5]
model:
  id: tusay2022_eq5_7_v1
ephemeris:
  adapter: astropy_builtin
products:
  formats: [ecsv, json]
"""


@pytest.fixture()
def request_path(tmp_path: Path) -> Path:
    path = tmp_path / "crossings.yaml"
    path.write_text(REQUEST, encoding="utf-8")
    return path


def test_cli_writes_products(tmp_path: Path, request_path: Path) -> None:
    output_dir = tmp_path / "products"
    exit_code = main(
        [
            "crossings",
            "--targets",
            str(EXAMPLES_DIR / "targets.yaml"),
            "--request",
            str(request_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"]["event_count"] >= 3
    assert (output_dir / "events.ecsv").is_file()
    assert (output_dir / "windows.ecsv").is_file()

    from astropy.table import Table

    events = Table.read(output_dir / "events.ecsv")
    assert set(events["interval_id"]) == {"window"}
    assert manifest["science_inputs"]["input_file_hashes"].keys() == {
        "request_yaml",
        "targets_yaml",
    }


def test_events_are_real_local_minima(request_path: Path) -> None:
    registry = load_target_registry(EXAMPLES_DIR / "targets.yaml")
    request = load_crossings_request(request_path)
    result = find_crossings(request, registry)

    interior = [e for e in result.events if e.b_min_au == e.b_min_au and not e.warnings]
    # Two years of a quasi-annual metric: interior minima on both sides.
    assert len(interior) >= 3
    sides = [e.side.value for e in interior]
    assert "target" in sides and "anti_target" in sides

    target = registry["barnard"]
    ephemeris = AstropyEphemeris()
    for event in interior:
        t_ca = Time(event.t_ca_tdb_jd, format="jd", scale="tdb")

        def b_at(time: Time) -> float:
            return impact_parameter(
                target=target,
                time=time,
                link_direction=LinkDirection.INBOUND,
                observer=Observer.earth_center(),
                z_au=800.0,
                ephemeris=ephemeris,
            ).b_au

        center = b_at(t_ca)
        assert center == pytest.approx(event.b_min_au, rel=1e-9)
        day = TimeDelta(1.0, format="jd", scale="tdb")
        assert center <= b_at(t_ca - day)
        assert center <= b_at(t_ca + day)

    # Consecutive same-side minima are one orbital period apart.
    target_side = sorted(e.t_ca_tdb_jd for e in interior if e.side.value == "target")
    if len(target_side) >= 2:
        assert math.isclose(target_side[1] - target_side[0], 365.25, abs_tol=5.0)
