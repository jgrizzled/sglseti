"""The ``sampled_state_v1`` target family (§2.1, roadmap item 9)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from astropy.table import Table
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris

from sglseti.errors import (
    ConfigError,
    EphemerisCoverageError,
    EphemerisError,
    GenerationError,
)
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    Role,
    SampledStateSpec,
    Target,
    Validity,
)
from sglseti.provenance import canonicalize, file_sha256, stable_hash
from sglseti.providers import (
    LinearAstrometryV1,
    SampledStateV1,
    TargetStateProvider,
    clear_provider_cache,
    resolve_target_state_provider,
)
from sglseti.targets import load_target_registry
from sglseti.uncertainty import target_uncertainty

MODEL = Tusay2022Eq57V1()
EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
T_O = Time("2021-11-06T00:00:00", scale="utc")


def make_astrometry() -> AstrometricState:
    return AstrometricState(
        ra_deg=10.0,
        dec_deg=20.0,
        pm_ra_cosdec_mas_per_yr=100.0,
        pm_dec_mas_per_yr=-50.0,
        reference_epoch_jyear=2016.0,
        reference_epoch_scale="tdb",
        source="unit test values",
        distance_pc=200_000.0 / AU_PER_PC,
        radial_velocity_km_s=0.0,
    )


def write_state_table(
    path: Path,
    epochs_jd: list[float],
    positions: list[tuple[float, float, float]],
) -> Path:
    Table(
        {
            "epoch_tdb_jd": epochs_jd,
            "x_au": [p[0] for p in positions],
            "y_au": [p[1] for p in positions],
            "z_au": [p[2] for p in positions],
        }
    ).write(path, format="ascii.ecsv", overwrite=True)
    return path


def linear_table(path: Path, *, start_jd: float, stop_jd: float, samples: int = 40) -> Path:
    """Tabulate the linear provider's own states: the equivalence oracle."""
    reference = LinearAstrometryV1(
        Target(
            target_id="oracle",
            display_name="oracle",
            endpoint_kind=EndpointKind.STAR,
            astrometry=make_astrometry(),
        )
    )
    epochs, positions = [], []
    for jd in np.linspace(start_jd, stop_jd, samples):
        state = reference.state_at(Time(jd, format="jd", scale="tdb"))
        unit = np.array(
            [
                np.cos(np.radians(state.dec_deg)) * np.cos(np.radians(state.ra_deg)),
                np.cos(np.radians(state.dec_deg)) * np.sin(np.radians(state.ra_deg)),
                np.sin(np.radians(state.dec_deg)),
            ]
        )
        epochs.append(float(jd))
        positions.append(tuple(state.distance_au * unit))
    return write_state_table(path, epochs, positions)


def sampled_target(
    path: Path,
    *,
    endpoint: EndpointKind = EndpointKind.STAR,
    epoch_semantics: str = "ssb_light_arrival_time",
    checksum: str | None = None,
) -> Target:
    return Target(
        target_id="sampled",
        display_name="Sampled endpoint",
        endpoint_kind=endpoint,
        astrometry=make_astrometry(),
        provider_id="sampled_state_v1",
        sampled_state=SampledStateSpec(
            path=str(path),
            checksum_sha256=checksum if checksum is not None else file_sha256(path),
            epoch_semantics=epoch_semantics,
            source="unit test sampled ephemeris",
        ),
    )


BASE_JD = float(T_O.tdb.jd)


@pytest.fixture()
def table(tmp_path: Path) -> Path:
    return linear_table(
        tmp_path / "sampled.ecsv", start_jd=BASE_JD - 400.0, stop_jd=BASE_JD + 400.0
    )


# ---------------------------------------------------------------------------
# Spec and registry validation
# ---------------------------------------------------------------------------


def test_spec_requires_checksum_and_known_semantics() -> None:
    with pytest.raises(ValueError, match="CHECKSUMMED"):
        SampledStateSpec(
            path="x.ecsv",
            checksum_sha256="",
            epoch_semantics="ssb_light_arrival_time",
            source="s",
        )
    with pytest.raises(ValueError, match="epoch_semantics must be one of"):
        SampledStateSpec(
            path="x.ecsv",
            checksum_sha256="sha256:ab",
            epoch_semantics="whatever",
            source="s",
        )


def test_target_provider_coherence(table: Path) -> None:
    with pytest.raises(ValueError, match="required by \\(and only by\\)"):
        Target(
            target_id="t",
            display_name="t",
            endpoint_kind=EndpointKind.STAR,
            astrometry=make_astrometry(),
            provider_id="sampled_state_v1",
        )
    linear_with_block = dict(
        target_id="t",
        display_name="t",
        endpoint_kind=EndpointKind.STAR,
        astrometry=make_astrometry(),
        sampled_state=SampledStateSpec(
            path=str(table),
            checksum_sha256=file_sha256(table),
            epoch_semantics="ssb_light_arrival_time",
            source="s",
        ),
    )
    with pytest.raises(ValueError, match="required by \\(and only by\\)"):
        Target(**linear_with_block)


def test_planet_endpoint_only_via_sampled_family(table: Path) -> None:
    target = sampled_target(table, endpoint=EndpointKind.PLANET)
    assert target.endpoint_kind is EndpointKind.PLANET
    with pytest.raises(ValueError, match="modeled only by sampled_state_v1"):
        Target(
            target_id="p",
            display_name="p",
            endpoint_kind=EndpointKind.PLANET,
            astrometry=make_astrometry(),
        )


def test_registry_v2_parses_sampled_state(tmp_path: Path, table: Path) -> None:
    data: dict[str, Any] = {
        "schema_version": 2,
        "targets": {
            "sampled": {
                "display_name": "Sampled endpoint",
                "endpoint_kind": "star",
                "state": {
                    "provider": "sampled_state_v1",
                    "astrometry": {
                        "frame": "icrs",
                        "ra_deg": 10.0,
                        "dec_deg": 20.0,
                        "pm_ra_cosdec_mas_per_yr": 100.0,
                        "pm_dec_mas_per_yr": -50.0,
                        "distance_pc": 200_000.0 / AU_PER_PC,
                        "radial_velocity_km_s": 0.0,
                        "reference_epoch_jyear": 2016.0,
                        "reference_epoch_scale": "tdb",
                        "source": "unit test values",
                    },
                    "sampled_state": {
                        "path": str(table),
                        "checksum_sha256": file_sha256(table),
                        "epoch_semantics": "ssb_light_arrival_time",
                        "source": "unit test sampled ephemeris",
                    },
                },
            }
        },
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    registry = load_target_registry(path)
    target = registry["sampled"]
    assert target.provider_id == "sampled_state_v1"
    assert target.sampled_state is not None
    # Round-trip through the normalized form.
    normalized = tmp_path / "normalized.yaml"
    normalized.write_text(yaml.safe_dump(registry.to_normalized_dict()), encoding="utf-8")
    reloaded = load_target_registry(normalized)
    assert reloaded["sampled"] == target
    # Missing checksum is a schema error, not a default.
    broken = copy.deepcopy(data)
    del broken["targets"]["sampled"]["state"]["sampled_state"]["checksum_sha256"]
    path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(ConfigError, match="checksum_sha256"):
        load_target_registry(path)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_plain_target_canonical_form_omits_defaults() -> None:
    """Default-valued fields never enter identities (generic rule)."""
    target = Target(
        target_id="t",
        display_name="t",
        endpoint_kind=EndpointKind.STAR,
        astrometry=make_astrometry(),
    )
    canonical = canonicalize(target)
    assert set(canonical["fields"]) == {
        "target_id",
        "display_name",
        "endpoint_kind",
        "astrometry",
    }


def test_sampled_identity_is_content_not_path(tmp_path: Path, table: Path) -> None:
    import shutil

    copied = tmp_path / "elsewhere.ecsv"
    shutil.copyfile(table, copied)
    assert stable_hash(sampled_target(table)) == stable_hash(sampled_target(copied))
    canonical = canonicalize(sampled_target(table))
    assert "path" not in canonical["fields"]["sampled_state"]["fields"]
    assert "checksum_sha256" in canonical["fields"]["sampled_state"]["fields"]


# ---------------------------------------------------------------------------
# Provider behavior
# ---------------------------------------------------------------------------


def test_sampled_states_match_the_tabulated_linear_motion(table: Path) -> None:
    clear_provider_cache()
    target = sampled_target(table)
    provider = resolve_target_state_provider(target)
    assert isinstance(provider, SampledStateV1)
    assert isinstance(provider, TargetStateProvider)
    linear = LinearAstrometryV1(target)
    for offset in (-350.0, -13.7, 0.0, 200.3):
        epoch = Time(BASE_JD + offset, format="jd", scale="tdb")
        sampled = provider.state_at(epoch)
        reference = linear.state_at(epoch)
        # A 40-node table over 800 days of near-linear cartesian motion
        # interpolates to sub-mas agreement with the underlying model.
        assert sampled.ra_deg == pytest.approx(reference.ra_deg, abs=1e-6)
        assert sampled.dec_deg == pytest.approx(reference.dec_deg, abs=1e-6)
        assert sampled.distance_au == pytest.approx(reference.distance_au, rel=1e-9)
    vector_states = provider.states_at(
        Time([BASE_JD - 350.0, BASE_JD + 200.3], format="jd", scale="tdb")
    )
    assert (
        vector_states[0].ra_deg
        == provider.state_at(Time(BASE_JD - 350.0, format="jd", scale="tdb")).ra_deg
    )


def test_sampled_metadata_declarations(table: Path) -> None:
    provider = SampledStateV1(sampled_target(table))
    assert provider.provider_id == "sampled_state_v1"
    assert provider.epoch_semantics == "ssb_light_arrival_time"
    assert provider.uncertainty_model == "not_propagated"
    assert provider.interpolation == "linear"
    assert provider.warnings == ()
    assert provider.propagation_span_years(T_O) is None
    low, high = provider.validity_interval_jyear
    assert low < 2021.8 < high
    assert provider.coverage.startswith("tdb_jd [")


def test_model_consumes_sampled_provider(table: Path) -> None:
    clear_provider_cache()
    target = sampled_target(table)
    solution = MODEL.target_direction(target, T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)
    linear_solution = MODEL.target_direction(
        Target(
            target_id="sampled",
            display_name="Sampled endpoint",
            endpoint_kind=EndpointKind.STAR,
            astrometry=make_astrometry(),
        ),
        T_O,
        1000.0,
        Role.ANTIPODE,
        EPHEMERIS,
    )
    assert solution.target_direction_icrs_ra_deg == pytest.approx(
        linear_solution.target_direction_icrs_ra_deg, abs=1e-6
    )
    assert solution.validity is not Validity.INVALID


def test_model_refuses_physical_event_semantics(table: Path) -> None:
    clear_provider_cache()
    target = sampled_target(table, epoch_semantics="physical_event_time")
    with pytest.raises(ValueError, match="epoch\\s+semantics"):
        MODEL.target_direction(target, T_O, 1000.0, Role.ANTIPODE, EPHEMERIS)


def test_out_of_coverage_epoch_raises(table: Path) -> None:
    clear_provider_cache()
    provider = SampledStateV1(sampled_target(table))
    with pytest.raises(EphemerisCoverageError, match="outside sampled-state table"):
        provider.state_at(Time(BASE_JD + 1000.0, format="jd", scale="tdb"))


def test_consistency_guard_rejects_wrong_file(tmp_path: Path) -> None:
    # A table pointing the opposite way on the sky: clearly the wrong file.
    wrong = write_state_table(
        tmp_path / "wrong.ecsv",
        [BASE_JD - 10.0, BASE_JD + 10.0],
        [(-200_000.0, 0.0, 0.0), (-200_000.0, 0.0, 1.0)],
    )
    with pytest.raises(EphemerisError, match="wrong file"):
        SampledStateV1(sampled_target(wrong))


def test_checksum_mismatch_rejected(table: Path) -> None:
    with pytest.raises(EphemerisError, match="checksum mismatch"):
        SampledStateV1(sampled_target(table, checksum="sha256:deadbeef"))


def test_uncertainty_sampling_refuses_sampled_targets(table: Path) -> None:
    with pytest.raises(GenerationError, match="sampled_state_v1"):
        target_uncertainty(sampled_target(table))
