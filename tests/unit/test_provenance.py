from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sglseti.provenance import (
    CANONICAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    build_manifest,
    canonical_json,
    canonicalize,
    file_sha256,
    request_id,
    stable_hash,
    stable_id,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


# Golden digest: freezes the canonical schema. If this test fails, the hash
# schema changed — bump CANONICAL_SCHEMA_VERSION and document the migration;
# never just update the string.
# Re-baselined 2026-08-18 for canonical schema v2 (the greenfield identity
# baseline adopted before first archival use); the version is part of the
# hashed envelope, so the bump moved every hash exactly once.
GOLDEN_HASH_A1 = "sha256:e49622992a3e20ca18fad0689ef2bcf5865151150e1ee9c65d0d349ebbbe9558"


def test_golden_hash_schema_v1() -> None:
    assert CANONICAL_SCHEMA_VERSION == 2
    assert stable_hash({"a": 1}) == GOLDEN_HASH_A1


def test_hash_format() -> None:
    digest = stable_hash([1, 2, 3])
    assert digest.startswith("sha256:")
    assert len(digest) == 7 + 64
    assert stable_id("x", [1, 2, 3]) == f"x-{digest[7:19]}"


def test_canonical_json_sorts_keys_deterministically() -> None:
    a = canonical_json({"b": 1, "a": {"d": 2, "c": 3}})
    b = canonical_json({"a": {"c": 3, "d": 2}, "b": 1})
    assert a == b == '{"a":{"c":3,"d":2},"b":1}'


def test_integral_floats_normalize_to_int() -> None:
    assert stable_hash({"z": 550.0}) == stable_hash({"z": 550})
    assert stable_hash({"z": 550.5}) != stable_hash({"z": 550})


def test_negative_zero_normalizes() -> None:
    assert stable_hash(-0.0) == stable_hash(0.0) == stable_hash(0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonicalize({"x": bad})


def test_enum_serializes_as_value() -> None:
    from sglseti.models import Role

    assert canonicalize(Role.RX) == "rx"
    assert stable_hash({"role": Role.RX}) == stable_hash({"role": "rx"})


def test_dataclass_type_distinguishes_identity() -> None:
    @dataclasses.dataclass(frozen=True)
    class A:
        x: int

    @dataclasses.dataclass(frozen=True)
    class B:
        x: int

    assert stable_hash(A(1)) != stable_hash(B(1))
    assert stable_hash(A(1)) == stable_hash(A(1))
    assert canonicalize(A(1)) == {"__dataclass__": "A", "fields": {"x": 1}}


def test_time_normalizes_across_scales() -> None:
    from astropy.time import Time

    utc = Time("2021-11-06T03:14:00", scale="utc")
    via_tdb = Time(utc.tdb.jd1, utc.tdb.jd2, format="jd", scale="tdb")
    assert stable_hash(utc) == stable_hash(via_tdb)
    assert stable_hash(utc) != stable_hash(utc + 1 * _u().s)
    # Normalization must not mutate the input.
    assert utc.precision != 9


def test_quantity_normalizes_across_units() -> None:
    u = _u()
    assert stable_hash(550 * u.au) == stable_hash((550 * u.au).to(u.km))
    assert stable_hash(550 * u.au) != stable_hash(551 * u.au)


def _u():  # local import keeps module import light for non-astropy tests
    from astropy import units

    return units


def test_paths_rejected(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="file_sha256"):
        canonicalize({"resource": tmp_path / "kernel.bsp"})


def test_sets_rejected() -> None:
    with pytest.raises(TypeError, match="unordered"):
        canonicalize({"roles": {"rx", "tx"}})


def test_file_sha256(tmp_path: Path) -> None:
    target = tmp_path / "resource.bin"
    target.write_bytes(b"sglseti")
    digest = file_sha256(target)
    # sha256 of b"sglseti", computed independently.
    import hashlib

    assert digest == "sha256:" + hashlib.sha256(b"sglseti").hexdigest()


def test_request_id_deterministic_and_science_sensitive(tmp_path: Path) -> None:
    from sglseti.config import load_request

    first = load_request(EXAMPLES / "historical.yaml")
    second = load_request(EXAMPLES / "historical.yaml")
    assert request_id(first) == request_id(second)
    assert request_id(first).startswith("req-")

    # Same science from a different directory -> same ID (path independence).
    import shutil

    shutil.copy(EXAMPLES / "historical.yaml", tmp_path / "historical.yaml")
    shutil.copy(EXAMPLES / "historical_epochs.ecsv", tmp_path / "historical_epochs.ecsv")
    moved = load_request(tmp_path / "historical.yaml")
    assert request_id(moved) == request_id(first)

    # A scientific change -> different ID.
    text = (EXAMPLES / "historical.yaml").read_text(encoding="utf-8")
    (tmp_path / "changed.yaml").write_text(
        text.replace("max_au: 2500.0", "max_au: 2400.0"), encoding="utf-8"
    )
    changed = load_request(tmp_path / "changed.yaml")
    assert request_id(changed) != request_id(first)


def test_manifest_separates_science_from_run() -> None:
    science = {"targets": ["barnard"], "z_min_au": 550.0}
    manifest_a = build_manifest(
        science_inputs=science,
        run_metadata={"generated_utc": "2026-08-17T00:00:00Z", "output_dir": "/tmp/a"},
    )
    manifest_b = build_manifest(
        science_inputs=science,
        run_metadata={"generated_utc": "2030-01-01T12:34:56Z", "output_dir": "/data/b"},
    )
    assert manifest_a["science_input_hash"] == manifest_b["science_input_hash"]
    assert manifest_a["science_input_hash"] == stable_hash(science)
    assert manifest_a["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest_a["canonical_schema_version"] == CANONICAL_SCHEMA_VERSION
    assert manifest_a["run"]["output_dir"] == "/tmp/a"
    # The manifest itself is JSON-serializable.
    json.dumps(manifest_a)


def test_registry_hash_uses_canonical_schema() -> None:
    from sglseti.targets import load_target_registry

    registry = load_target_registry(EXAMPLES / "targets.yaml")
    assert registry.source_hash == stable_hash(registry.to_normalized_dict())
