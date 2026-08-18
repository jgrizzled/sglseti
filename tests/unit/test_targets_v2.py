"""Registry schema v2: strict loading, provider coherence, identity."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from sglseti.errors import ConfigError
from sglseti.models import CovarianceKind, OrbitComponent
from sglseti.targets import load_target_registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

LINEAR_ASTROMETRY: dict[str, Any] = {
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

ORBIT: dict[str, Any] = {
    "period_yr": 79.91,
    "periastron_epoch_jyear": 1955.66,
    "eccentricity": 0.524,
    "semimajor_axis_arcsec": 17.66,
    "inclination_deg": 79.32,
    "ascending_node_deg": 204.85,
    "arg_periastron_deg": 232.3,
    "mass_fraction_secondary": 0.4617,
    "component": "primary",
    "source": "Pourbaix & Boffin 2016 via Akeson et al. 2021 Table 8",
}


def write_registry(tmp_path: Path, targets: dict[str, Any], version: int = 2) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": version, "targets": targets}), encoding="utf-8"
    )
    return path


def linear_v2_target(**extra: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "display_name": "Test Star",
        "endpoint_kind": "star",
        "state": {
            "provider": "linear_astrometry_v1",
            "astrometry": copy.deepcopy(LINEAR_ASTROMETRY),
        },
    }
    target.update(extra)
    return target


def orbit_v2_target(**extra: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "display_name": "Component A",
        "endpoint_kind": "component",
        "state": {
            "provider": "two_body_orbit_v1",
            "astrometry": copy.deepcopy(LINEAR_ASTROMETRY),
            "orbit": copy.deepcopy(ORBIT),
        },
    }
    target.update(extra)
    return target


def test_example_v2_registry_loads() -> None:
    registry = load_target_registry(EXAMPLES / "targets_advanced.yaml")
    assert registry.ids == ("alpha-cen-ab", "alpha-cen-a", "accel-demo")
    barycenter = registry["alpha-cen-ab"]
    assert barycenter.provider_id == "two_body_orbit_v1"
    assert barycenter.orbit is not None
    assert barycenter.orbit.component is OrbitComponent.BARYCENTER
    assert barycenter.identifiers[0].version == "2016, A&A 586, A90"
    provenance = {p.parameter: p for p in barycenter.parameter_provenance}
    assert provenance["parallax_mas"].uncertainty == 1.3
    assert provenance["parallax_mas"].unit == "mas"
    accel = registry["accel-demo"]
    assert accel.provider_id == "acceleration_astrometry_v1"
    assert accel.acceleration is not None
    assert accel.covariance is not None
    assert accel.covariance.kind is CovarianceKind.CORRELATION
    assert "accelerating_system" in accel.flags


def test_v2_normalized_round_trip(tmp_path: Path) -> None:
    original = load_target_registry(EXAMPLES / "targets_advanced.yaml")
    normalized = original.to_normalized_dict()
    assert normalized["schema_version"] == 2
    dumped = tmp_path / "normalized.yaml"
    dumped.write_text(yaml.safe_dump(normalized), encoding="utf-8")
    reloaded = load_target_registry(dumped)
    # Normalization sorts targets by ID; identity and content are unchanged.
    assert sorted(reloaded.targets, key=lambda t: t.target_id) == sorted(
        original.targets, key=lambda t: t.target_id
    )
    assert reloaded.source_hash == original.source_hash


def test_v2_metadata_changes_identity(tmp_path: Path) -> None:
    base = load_target_registry(write_registry(tmp_path, {"t": linear_v2_target()}))
    enriched_target = linear_v2_target(
        identifiers=[{"catalog": "Gaia", "id": "123", "version": "DR3"}]
    )
    enriched = load_target_registry(
        write_registry(tmp_path, {"t": enriched_target})
    )
    assert enriched.to_normalized_dict()["schema_version"] == 2
    assert enriched.source_hash != base.source_hash


def test_missing_provider_rejected(tmp_path: Path) -> None:
    target = linear_v2_target()
    del target["state"]["provider"]
    with pytest.raises(ConfigError, match=r"state\.provider"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_unknown_state_key_rejected(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["orbits"] = {}
    with pytest.raises(ConfigError, match="unknown key"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_astrometry_block_at_target_level_rejected_in_v2(tmp_path: Path) -> None:
    target = linear_v2_target(astrometry=copy.deepcopy(LINEAR_ASTROMETRY))
    with pytest.raises(ConfigError, match="unknown key"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_orbit_with_linear_provider_rejected(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["orbit"] = copy.deepcopy(ORBIT)
    with pytest.raises(ConfigError, match="required by \\(and only by\\)"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_orbit_provider_without_orbit_rejected(tmp_path: Path) -> None:
    target = orbit_v2_target()
    del target["state"]["orbit"]
    with pytest.raises(ConfigError, match="orbit"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_orbit_component_endpoint_mismatch_rejected(tmp_path: Path) -> None:
    target = orbit_v2_target(endpoint_kind="barycenter")
    with pytest.raises(ConfigError, match="does not match"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_orbit_star_endpoint_rejected(tmp_path: Path) -> None:
    target = orbit_v2_target(endpoint_kind="star")
    with pytest.raises(ConfigError, match="not modeled by provider"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_planet_endpoint_rejected(tmp_path: Path) -> None:
    target = linear_v2_target(endpoint_kind="planet")
    with pytest.raises(ConfigError, match="future provider family"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_accelerating_flag_needs_acceleration_family(tmp_path: Path) -> None:
    linear_flagged = linear_v2_target(flags=["accelerating_system"])
    with pytest.raises(ConfigError, match="cannot model"):
        load_target_registry(write_registry(tmp_path, {"t": linear_flagged}))
    accel = linear_v2_target(flags=["accelerating_system"])
    accel["state"]["provider"] = "acceleration_astrometry_v1"
    accel["state"]["acceleration"] = {
        "accel_ra_cosdec_mas_per_yr2": 0.5,
        "accel_dec_mas_per_yr2": -0.2,
        "source": "demonstration",
    }
    registry = load_target_registry(write_registry(tmp_path, {"t": accel}))
    assert registry["t"].provider_id == "acceleration_astrometry_v1"


def test_provenance_for_absent_parameter_rejected(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["provenance"] = {
        "period_yr": {"source": "nope"},
    }
    with pytest.raises(ConfigError, match="does not name a value present"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_provenance_uncertainty_requires_unit(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["provenance"] = {
        "parallax_mas": {"source": "catalog", "uncertainty": 0.3},
    }
    with pytest.raises(ConfigError, match="requires an explicit unit"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_covariance_asymmetry_rejected(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["covariance"] = {
        "parameters": ["ra", "dec"],
        "units": ["mas", "mas"],
        "kind": "covariance",
        "matrix": [[1.0, 0.2], [0.3, 1.0]],
    }
    with pytest.raises(ConfigError, match="symmetric"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_correlation_diagonal_must_be_one(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["covariance"] = {
        "parameters": ["ra", "dec"],
        "units": ["mas", "mas"],
        "kind": "correlation",
        "matrix": [[1.0, 0.2], [0.2, 0.9]],
    }
    with pytest.raises(ConfigError, match="diagonal must be exactly 1"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_covariance_units_must_match_parameters(tmp_path: Path) -> None:
    target = linear_v2_target()
    target["state"]["covariance"] = {
        "parameters": ["ra", "dec"],
        "units": ["mas"],
        "kind": "covariance",
        "matrix": [[1.0, 0.0], [0.0, 1.0]],
    }
    with pytest.raises(ConfigError, match="2 parameters but 1 units"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_identifier_requires_version(tmp_path: Path) -> None:
    target = linear_v2_target(identifiers=[{"catalog": "Gaia", "id": "123"}])
    with pytest.raises(ConfigError, match=r"version.*non-empty string"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_unknown_orbit_component_rejected(tmp_path: Path) -> None:
    target = orbit_v2_target()
    target["state"]["orbit"]["component"] = "tertiary"
    with pytest.raises(ConfigError, match="unknown component"):
        load_target_registry(write_registry(tmp_path, {"t": target}))


def test_missing_rv_flag_policy_applies_in_v2(tmp_path: Path) -> None:
    target = linear_v2_target()
    del target["state"]["astrometry"]["radial_velocity_km_s"]
    path = write_registry(tmp_path, {"t": target})
    with pytest.raises(ConfigError, match="radial_velocity_km_s"):
        load_target_registry(path)
    registry = load_target_registry(path, missing_radial_velocity="flag")
    assert registry["t"].astrometry.radial_velocity_km_s is None
    assert "missing_radial_velocity" in registry["t"].flags
