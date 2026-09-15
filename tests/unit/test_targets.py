from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sglseti.errors import ConfigError
from sglseti.targets import MISSING_RV_FLAG, TargetRegistry, load_target_registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

VALID_ASTROMETRY: dict[str, object] = {
    "frame": "icrs",
    "ra_deg": 269.45207695861876,
    "dec_deg": 4.693364966576667,
    "parallax_mas": 546.9759,
    "pm_ra_cosdec_mas_per_yr": -801.551,
    "pm_dec_mas_per_yr": 10362.394,
    "radial_velocity_km_s": -110.11,
    "reference_epoch_jyear": 2000.0,
    "reference_epoch_scale": "tcb",
    "source": "example catalog snapshot",
}


def make_registry_yaml(
    tmp_path: Path, astrometry: dict[str, object], **target_extra: object
) -> Path:
    target: dict[str, object] = {
        "display_name": "Test Star",
        "endpoint_kind": "star",
        "state": {"provider": "linear_astrometry_v1", "astrometry": astrometry},
    }
    target.update(target_extra)
    data = {"schema_version": 2, "targets": {"test-star": target}}
    path = tmp_path / "targets.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_example_registry_loads() -> None:
    registry = load_target_registry(EXAMPLES / "targets.yaml")
    assert registry.ids == ("barnard",)
    barnard = registry["barnard"]
    assert barnard.endpoint_kind == "star"
    assert barnard.astrometry.reference_epoch_scale == "tcb"
    assert registry.source_hash.startswith("sha256:")


def test_registry_mapping_behavior() -> None:
    registry = load_target_registry(EXAMPLES / "targets.yaml")
    assert "barnard" in registry
    assert len(registry) == 1
    with pytest.raises(KeyError, match="unknown target ID 'nope'"):
        registry["nope"]


def test_schema_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "registry.yaml"
    path.write_text("schema_version: 1\ntargets: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="schema_version: must be 2"):
        load_target_registry(path)


def test_top_level_not_mapping(tmp_path: Path) -> None:
    path = tmp_path / "targets.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_target_registry(path)


def test_empty_targets(tmp_path: Path) -> None:
    path = tmp_path / "targets.yaml"
    path.write_text("schema_version: 2\ntargets: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty mapping"):
        load_target_registry(path)


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="file not found"):
        load_target_registry("/nonexistent/targets.yaml")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), "not-a-number", None])
def test_non_finite_or_non_numeric_values(tmp_path: Path, bad_value: object) -> None:
    astrometry = dict(VALID_ASTROMETRY, ra_deg=bad_value)
    with pytest.raises(ConfigError, match=r"astrometry\.ra_deg"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


@pytest.mark.parametrize(
    ("field", "value", "pattern"),
    [
        ("ra_deg", 360.0, r"\[0, 360\)"),
        ("ra_deg", -1.0, r"\[0, 360\)"),
        ("dec_deg", 91.0, r"\[-90, 90\]"),
        ("parallax_mas", -5.0, "positive"),
        ("parallax_mas", 0.0, "positive"),
        ("reference_epoch_jyear", 1500.0, r"\[1800, 2200\]"),
    ],
)
def test_out_of_range_astrometry(tmp_path: Path, field: str, value: float, pattern: str) -> None:
    astrometry = dict(VALID_ASTROMETRY, **{field: value})
    with pytest.raises(ConfigError, match=pattern):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_missing_source(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["source"]
    with pytest.raises(ConfigError, match="source.*required"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_source_unspecified_rejected(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY, source="unspecified")
    with pytest.raises(ConfigError, match="provenance"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_missing_frame(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["frame"]
    with pytest.raises(ConfigError, match=r"astrometry\.frame"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_non_icrs_frame_rejected(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY, frame="fk5")
    with pytest.raises(ConfigError, match="icrs"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_missing_reference_epoch_scale(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["reference_epoch_scale"]
    with pytest.raises(ConfigError, match="reference_epoch_scale"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_invalid_reference_epoch_scale(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY, reference_epoch_scale="gps")
    with pytest.raises(ConfigError, match="reference_epoch_scale"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_parallax_and_distance_both_given(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY, distance_pc=1.83)
    with pytest.raises(ConfigError, match="exactly one of parallax_mas and distance_pc"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_neither_parallax_nor_distance(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["parallax_mas"]
    with pytest.raises(ConfigError, match="exactly one of parallax_mas and distance_pc"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_distance_pc_alone_accepted(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["parallax_mas"]
    astrometry["distance_pc"] = 1.83
    registry = load_target_registry(make_registry_yaml(tmp_path, astrometry))
    assert registry["test-star"].astrometry.distance_pc == 1.83


def test_missing_radial_velocity_default_error(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["radial_velocity_km_s"]
    with pytest.raises(ConfigError, match="radial_velocity_km_s.*required"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_missing_radial_velocity_flag_policy(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY)
    del astrometry["radial_velocity_km_s"]
    registry = load_target_registry(
        make_registry_yaml(tmp_path, astrometry), missing_radial_velocity="flag"
    )
    target = registry["test-star"]
    assert target.astrometry.radial_velocity_km_s is None
    assert MISSING_RV_FLAG in target.flags


def test_unknown_astrometry_key_rejected(tmp_path: Path) -> None:
    astrometry = dict(VALID_ASTROMETRY, paralax_mas=5.0)  # typo must not be dropped
    del astrometry["parallax_mas"]
    with pytest.raises(ConfigError, match="unknown key"):
        load_target_registry(make_registry_yaml(tmp_path, astrometry))


def test_missing_endpoint_kind(tmp_path: Path) -> None:
    path = tmp_path / "targets.yaml"
    data = {
        "schema_version": 2,
        "targets": {
            "test-star": {
                "state": {
                    "provider": "linear_astrometry_v1",
                    "astrometry": dict(VALID_ASTROMETRY),
                }
            }
        },
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="endpoint_kind.*required"):
        load_target_registry(path)


def test_endpoint_kind_other_rejected(tmp_path: Path) -> None:
    path = make_registry_yaml(tmp_path, dict(VALID_ASTROMETRY), endpoint_kind="other")
    with pytest.raises(ConfigError, match="not modeled by provider"):
        load_target_registry(path)


@pytest.mark.parametrize("flag", ["unresolved_binary", "accelerating_system"])
def test_unsupported_motion_flags_rejected(tmp_path: Path, flag: str) -> None:
    path = make_registry_yaml(tmp_path, dict(VALID_ASTROMETRY), flags=[flag])
    with pytest.raises(ConfigError, match="cannot model"):
        load_target_registry(path)


def test_duplicate_target_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "targets.yaml"
    astro = yaml.safe_dump(
        {
            "state": {
                "provider": "linear_astrometry_v1",
                "astrometry": dict(VALID_ASTROMETRY),
            },
            "endpoint_kind": "star",
        }
    )
    indented = "\n".join(f"    {line}" for line in astro.splitlines())
    path.write_text(
        "schema_version: 2\ntargets:\n  dupe:\n" + indented + "\n  dupe:\n" + indented + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate mapping key"):
        load_target_registry(path)


def test_normalized_round_trip(tmp_path: Path) -> None:
    original = load_target_registry(EXAMPLES / "targets.yaml")
    dumped = tmp_path / "normalized.yaml"
    dumped.write_text(yaml.safe_dump(original.to_normalized_dict()), encoding="utf-8")
    reloaded = load_target_registry(dumped)
    assert reloaded.targets == original.targets
    assert reloaded.source_hash == original.source_hash


def test_source_hash_ignores_formatting_but_not_science(tmp_path: Path) -> None:
    base = load_target_registry(make_registry_yaml(tmp_path, dict(VALID_ASTROMETRY)))
    # Formatting/comment changes do not alter the hash.
    reformatted = tmp_path / "reformatted.yaml"
    reformatted.write_text(
        "# a comment\n" + yaml.safe_dump(base.to_normalized_dict(), default_flow_style=False),
        encoding="utf-8",
    )
    assert load_target_registry(reformatted).source_hash == base.source_hash
    # A scientific value change does.
    changed = dict(VALID_ASTROMETRY, parallax_mas=500.0)
    other = load_target_registry(make_registry_yaml(tmp_path, changed))
    assert other.source_hash != base.source_hash


def test_from_yaml_classmethod() -> None:
    registry = TargetRegistry.from_yaml(EXAMPLES / "targets.yaml")
    assert registry.ids == ("barnard",)
