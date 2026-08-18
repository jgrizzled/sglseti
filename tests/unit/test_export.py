from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from support import FakeEphemeris, build_small_result

from sglseti.export import (
    POINTING_COLUMNS,
    RESULT_SCHEMA_VERSION,
    SAMPLE_COLUMNS,
    write_products,
)
from sglseti.provenance import file_sha256

GENERATED = "2026-08-17T12:00:00+00:00"


@pytest.fixture(scope="module")
def result():
    return build_small_result()


@pytest.fixture(scope="module")
def planned_result():
    return build_small_result(planned=True)


def write(result, tmp_path: Path, **kwargs):
    return write_products(result, tmp_path, generated_utc=GENERATED, **kwargs)


class TestEcsv:
    def test_round_trip_columns_units_metadata(self, result, tmp_path: Path) -> None:
        from astropy.table import Table

        written = write(result, tmp_path)
        table = Table.read(written["samples_ecsv"], format="ascii.ecsv")
        assert tuple(table.colnames) == SAMPLE_COLUMNS
        assert len(table) == len(result.samples)
        assert str(table["z_au"].unit) == "AU"
        assert str(table["icrs_ra_deg"].unit) == "deg"
        assert str(table["rate_ra_cosdec_arcsec_per_hr"].unit) == "arcsec / h"
        assert table.meta["calculation_id"] == result.calculation_id
        assert table.meta["result_schema_version"] == RESULT_SCHEMA_VERSION
        # Values survive the round trip.
        assert float(table["icrs_ra_deg"][0]) == pytest.approx(
            result.samples[0].icrs_ra_deg
        )
        assert str(table["epoch_id"][0]) == result.samples[0].epoch_id

    def test_corridor_table_references_samples(self, result, tmp_path: Path) -> None:
        from astropy.table import Table

        written = write(result, tmp_path)
        corridors = Table.read(written["corridors_ecsv"], format="ascii.ecsv")
        samples = Table.read(written["samples_ecsv"], format="ascii.ecsv")
        assert len(corridors) == len(result.corridors)
        first = corridors[0]
        referenced = str(first["sample_ids"]).split(";")
        assert int(first["sample_count"]) == len(referenced)
        in_table = {
            str(row["sample_id"])
            for row in samples
            if str(row["corridor_id"]) == str(first["corridor_id"])
        }
        assert set(referenced) == in_table


class TestJson:
    def test_schema_and_round_trip(self, result, tmp_path: Path) -> None:
        written = write(result, tmp_path)
        document = json.loads(written["result_json"].read_text(encoding="utf-8"))
        assert document["result_schema_version"] == RESULT_SCHEMA_VERSION
        assert document["calculation_id"] == result.calculation_id
        assert set(document) == {
            "result_schema_version",
            "calculation_id",
            "request",
            "warnings",
            "samples",
            "corridors",
            "visibility",
            "pointings",
        }
        assert len(document["samples"]) == len(result.samples)
        sample = document["samples"][0]
        assert sample["role"] in ("rx", "tx")
        assert sample["icrs_ra_deg"] == pytest.approx(result.samples[0].icrs_ra_deg)
        # The embedded request never carries a filesystem path.
        assert "path" not in json.dumps(document["request"])

    def test_nan_becomes_null(self, tmp_path: Path) -> None:
        limited = FakeEphemeris(
            (0.004, -0.002, 0.001),
            (0.558, -0.744, -0.323),
            coverage_jd=(2459000.0, 2459600.0),  # excludes epoch e2
        )
        result = build_small_result(ephemeris=limited)
        written = write(result, tmp_path)
        document = json.loads(written["result_json"].read_text(encoding="utf-8"))
        invalid = [s for s in document["samples"] if s["validity"] == "invalid"]
        assert invalid
        assert all(s["icrs_ra_deg"] is None for s in invalid)


class TestCsv:
    def test_stable_header_and_determinism(self, result, tmp_path: Path) -> None:
        written = write(result, tmp_path / "a")
        header = (
            written["samples_csv"].read_text(encoding="utf-8").splitlines()[0]
        )
        assert header == ",".join(SAMPLE_COLUMNS)
        again = write(result, tmp_path / "b")
        assert (
            written["samples_csv"].read_bytes() == again["samples_csv"].read_bytes()
        )

    def test_pointings_csv_when_planned(self, planned_result, tmp_path: Path) -> None:
        written = write(planned_result, tmp_path)
        header = (
            written["pointings_csv"].read_text(encoding="utf-8").splitlines()[0]
        )
        assert header == ",".join(POINTING_COLUMNS)
        # None fields (e.g. propagated width) serialize as empty cells.
        rows = written["pointings_csv"].read_text(encoding="utf-8").splitlines()[1:]
        index = POINTING_COLUMNS.index("propagated_half_width_arcsec")
        assert all(row.split(",")[index] == "" for row in rows)


class TestDs9:
    def test_syntax_and_counts(self, planned_result, tmp_path: Path) -> None:
        written = write(planned_result, tmp_path)
        text = written["regions_ds9"].read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0] == "# Region file format: DS9 version 4.1"
        assert "fk5" in lines
        assert any("ASSUMED half-widths" in line for line in lines)
        circle = re.compile(r'^circle\(-?[\d.]+,-?[\d.]+,[\d.]+"\) # ')
        circles = [line for line in lines if circle.match(line)]
        polyline = re.compile(r"^line\(-?[\d.]+,-?[\d.]+,-?[\d.]+,-?[\d.]+\) # ")
        segments = [line for line in lines if polyline.match(line)]
        valid_samples = [
            s for s in planned_result.samples if math.isfinite(s.icrs_ra_deg)
        ]
        assert len(circles) == len(valid_samples) + len(planned_result.pointings)
        expected_segments = sum(
            max(0, len(c.samples) - 1) for c in planned_result.corridors
        )
        assert len(segments) == expected_segments

    def test_invalid_samples_omitted_and_counted(self, tmp_path: Path) -> None:
        limited = FakeEphemeris(
            (0.004, -0.002, 0.001),
            (0.558, -0.744, -0.323),
            coverage_jd=(2459000.0, 2459600.0),
        )
        result = build_small_result(ephemeris=limited)
        written = write(result, tmp_path)
        text = written["regions_ds9"].read_text(encoding="utf-8")
        assert "# 6 invalid sample(s) omitted" in text
        assert "nan" not in text

    def test_request_validation_refuses_ds9_without_width(self) -> None:
        with pytest.raises(ValueError, match="assumed_half_width_arcsec"):
            build_small_result(assumed_half_width_arcsec=None)


class TestManifest:
    def test_science_hash_independent_of_run_circumstance(
        self, result, tmp_path: Path
    ) -> None:
        first = write(result, tmp_path / "a")
        second = write_products(
            result, tmp_path / "b", generated_utc="2030-01-01T00:00:00+00:00"
        )
        manifest_a = json.loads(first["manifest_json"].read_text(encoding="utf-8"))
        manifest_b = json.loads(second["manifest_json"].read_text(encoding="utf-8"))
        assert manifest_a["science_input_hash"] == manifest_b["science_input_hash"]
        assert manifest_a["run"]["generated_utc"] != manifest_b["run"]["generated_utc"]

    def test_output_files_cross_reference(self, result, tmp_path: Path) -> None:
        written = write(
            result, tmp_path, input_file_hashes={"targets_yaml": "sha256:abc"}
        )
        manifest = json.loads(written["manifest_json"].read_text(encoding="utf-8"))
        for label, checksum in manifest["run"]["output_files"].items():
            assert file_sha256(written[label]) == checksum
        assert set(manifest["run"]["output_files"]) == set(written) - {"manifest_json"}
        science = manifest["science_inputs"]
        assert science["input_file_hashes"] == {"targets_yaml": "sha256:abc"}
        assert science["calculation_id"] == result.calculation_id
        assert science["ephemeris_ids"] == ["fake_fixture_ephemeris"]
        assert science["conventions"]["catalog_epoch_semantics"] == (
            "ssb_light_arrival_time"
        )
        assert "sglseti" in manifest["run"]["versions"]


def test_exporters_do_not_import_geometry() -> None:
    import subprocess
    import sys

    probe = (
        "import sys\n"
        "import sglseti.export\n"
        "for module in ('sglseti.geometry', 'sglseti.ephemeris', 'sglseti.generate'):\n"
        "    assert module not in sys.modules, module\n"
    )
    subprocess.run([sys.executable, "-c", probe], check=True)
