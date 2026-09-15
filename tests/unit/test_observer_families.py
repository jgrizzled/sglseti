"""Observer-state provider families (§2.4, roadmap item 8).

Covers the four new families (Solar-System body, tabular spacecraft,
SPICE spacecraft, programmatic), the extended Observer spec validation,
the backward-compatible canonical identity (existing calculation IDs must
not move), and path-independence of new-kind identities.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from astropy.table import Table
from astropy.time import Time
from support import AU_PER_PC, FakeEphemeris

from sglseti.config import load_request
from sglseti.errors import (
    ConfigError,
    EphemerisCoverageError,
    EphemerisError,
    GenerationError,
)
from sglseti.generate import plan_calculation
from sglseti.geometry import observer_barycentric_au
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    Epoch,
    GeometryRequest,
    Observer,
    ObserverKind,
    OutputFormat,
    RelayRange,
    SamplingKind,
    SamplingSpec,
    Target,
    TimeList,
)
from sglseti.provenance import canonicalize, file_sha256, stable_hash
from sglseti.providers import (
    ProgrammaticObserverV1,
    SolarSystemBodyObserverV1,
    TabularSpacecraftObserverV1,
    clear_provider_cache,
    register_programmatic_observer,
    resolve_observer_state_provider,
    unregister_programmatic_observer,
)
from sglseti.targets import TargetRegistry

EPHEMERIS = FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323))
T_O = Time("2021-11-06T00:00:00", scale="utc")


# ---------------------------------------------------------------------------
# Observer spec validation and canonical identity
# ---------------------------------------------------------------------------


def test_observer_kind_field_coherence() -> None:
    with pytest.raises(ValueError, match="requires a body name"):
        Observer(observer_id="x", kind=ObserverKind.SOLAR_SYSTEM_BODY)
    with pytest.raises(ValueError, match="requires a path"):
        Observer(observer_id="x", kind=ObserverKind.SPACECRAFT_TABLE)
    with pytest.raises(ValueError, match="requires a spice_target"):
        Observer(observer_id="x", kind=ObserverKind.SPACECRAFT_SPICE, path="a.bsp")
    with pytest.raises(ValueError, match="requires checksum_sha256"):
        Observer(observer_id="x", kind=ObserverKind.SPACECRAFT_TABLE, path="a.ecsv")
    with pytest.raises(ValueError, match="caller-declared identity"):
        Observer(observer_id="x", kind=ObserverKind.PROGRAMMATIC)
    with pytest.raises(ValueError, match="does not take"):
        Observer.earth_center().__class__(
            observer_id="x", kind=ObserverKind.EARTH_CENTER, body="mars"
        )
    with pytest.raises(ValueError, match="does not take"):
        Observer(
            observer_id="x",
            kind=ObserverKind.SOLAR_SYSTEM_BODY,
            body="mars",
            path="stray.ecsv",
        )
    with pytest.raises(ValueError, match="lowercase"):
        Observer.solar_system_body("Mars")


def test_canonical_form_omits_defaults_and_paths(tmp_path: Path) -> None:
    """The generic canonical rules: default fields and paths never appear."""
    assert canonicalize(Observer.earth_center())["fields"] == {
        "observer_id": "earth-center",
        "kind": "earth_center",
    }
    path = tmp_path / "craft.ecsv"
    path.write_text("x", encoding="utf-8")
    observer = Observer.spacecraft_table("craft", str(path), checksum_sha256=file_sha256(path))
    canonical = canonicalize(observer)
    assert "path" not in canonical["fields"]
    assert canonical["fields"]["checksum_sha256"].startswith("sha256:")


# ---------------------------------------------------------------------------
# Solar-System body family
# ---------------------------------------------------------------------------


def test_solar_system_body_provider() -> None:
    clear_provider_cache()
    observer = Observer.solar_system_body("moon")
    provider = resolve_observer_state_provider(observer, EPHEMERIS)
    assert isinstance(provider, SolarSystemBodyObserverV1)
    state = provider.state_at(T_O)
    assert np.allclose(state.position_au, EPHEMERIS.moon_barycentric_au(T_O))
    assert np.allclose(observer_barycentric_au(observer, T_O, EPHEMERIS), state.position_au)
    positions = provider.positions_au(Time([2021.0, 2022.0], format="jyear"))
    assert positions.shape == (2, 3)
    with pytest.raises(EphemerisError, match="no body 'mars'"):
        resolve_observer_state_provider(Observer.solar_system_body("mars"), EPHEMERIS).state_at(T_O)


# ---------------------------------------------------------------------------
# Tabular spacecraft family
# ---------------------------------------------------------------------------


def write_table(
    path: Path,
    epochs_jd: list[float],
    positions: list[tuple[float, float, float]],
    velocities: list[tuple[float, float, float]] | None = None,
) -> Path:
    columns: dict[str, Any] = {
        "epoch_tdb_jd": epochs_jd,
        "x_au": [p[0] for p in positions],
        "y_au": [p[1] for p in positions],
        "z_au": [p[2] for p in positions],
    }
    if velocities is not None:
        columns["vx_au_per_day"] = [v[0] for v in velocities]
        columns["vy_au_per_day"] = [v[1] for v in velocities]
        columns["vz_au_per_day"] = [v[2] for v in velocities]
    Table(columns).write(path, format="ascii.ecsv", overwrite=True)
    return path


def test_tabular_linear_interpolation(tmp_path: Path) -> None:
    clear_provider_cache()
    path = write_table(
        tmp_path / "craft.ecsv",
        [2459000.0, 2459010.0],
        [(1.0, 2.0, 3.0), (2.0, 4.0, 6.0)],
    )
    provider = resolve_observer_state_provider(
        Observer.spacecraft_table("craft", str(path), checksum_sha256=file_sha256(path)),
        EPHEMERIS,
    )
    assert isinstance(provider, TabularSpacecraftObserverV1)
    assert provider.interpolation == "linear"
    assert provider.coverage.startswith("tdb_jd [2459000")
    at_node = provider.state_at(Time(2459000.0, format="jd", scale="tdb"))
    assert at_node.position_au == (1.0, 2.0, 3.0)
    assert at_node.velocity_au_per_day is None
    midpoint = provider.state_at(Time(2459005.0, format="jd", scale="tdb"))
    assert midpoint.position_au == pytest.approx((1.5, 3.0, 4.5))
    with pytest.raises(EphemerisCoverageError, match="outside spacecraft table"):
        provider.state_at(Time(2459020.0, format="jd", scale="tdb"))


def test_tabular_hermite_reproduces_a_cubic(tmp_path: Path) -> None:
    """Cubic Hermite interpolation is exact for cubic trajectories."""
    clear_provider_cache()

    def position(t_days: float) -> tuple[float, float, float]:
        return (
            1.0 + 0.1 * t_days - 0.002 * t_days**2 + 1e-4 * t_days**3,
            -0.5 + 0.05 * t_days,
            0.02 * t_days**2,
        )

    def velocity(t_days: float) -> tuple[float, float, float]:
        return (
            0.1 - 0.004 * t_days + 3e-4 * t_days**2,
            0.05,
            0.04 * t_days,
        )

    base_jd = 2459000.0
    nodes = [0.0, 7.0, 14.0, 21.0]
    path = write_table(
        tmp_path / "cubic.ecsv",
        [base_jd + t for t in nodes],
        [position(t) for t in nodes],
        [velocity(t) for t in nodes],
    )
    provider = resolve_observer_state_provider(
        Observer.spacecraft_table("cubic", str(path), checksum_sha256=file_sha256(path)),
        EPHEMERIS,
    )
    assert provider.interpolation == "cubic_hermite"
    for t_days in (1.7, 6.999, 10.5, 20.3):
        state = provider.state_at(Time(base_jd + t_days, format="jd", scale="tdb"))
        # abs=1e-9: Time stores ~2e-10 day quantization at this JD, far
        # below interpolation error scales but above exact float identity.
        assert state.position_au == pytest.approx(position(t_days), abs=1e-9)
        assert state.velocity_au_per_day == pytest.approx(velocity(t_days), abs=1e-9)
    vector = provider.positions_au(Time([base_jd + 1.7, base_jd + 10.5], format="jd", scale="tdb"))
    assert vector[0] == pytest.approx(position(1.7), abs=1e-9)


def test_tabular_identity_is_content_not_path(tmp_path: Path) -> None:
    clear_provider_cache()
    first = write_table(tmp_path / "a.ecsv", [2459000.0, 2459010.0], [(1, 2, 3), (2, 4, 6)])
    second = tmp_path / "renamed.ecsv"
    shutil.copyfile(first, second)
    provider_a = TabularSpacecraftObserverV1(
        Observer.spacecraft_table("craft", str(first), checksum_sha256=file_sha256(first))
    )
    provider_b = TabularSpacecraftObserverV1(
        Observer.spacecraft_table("craft", str(second), checksum_sha256=file_sha256(second))
    )
    assert provider_a.content_hash == provider_b.content_hash


def test_tabular_rejects_bad_tables(tmp_path: Path) -> None:
    path = write_table(tmp_path / "backwards.ecsv", [2459010.0, 2459000.0], [(1, 2, 3), (2, 4, 6)])
    with pytest.raises(EphemerisError, match="strictly increasing"):
        TabularSpacecraftObserverV1(
            Observer.spacecraft_table("craft", str(path), checksum_sha256=file_sha256(path))
        )
    with pytest.raises(EphemerisError, match="checksum mismatch"):
        TabularSpacecraftObserverV1(
            Observer.spacecraft_table(
                "craft",
                str(
                    write_table(
                        tmp_path / "ok.ecsv",
                        [2459000.0, 2459010.0],
                        [(1, 2, 3), (2, 4, 6)],
                    )
                ),
                checksum_sha256="sha256:deadbeef",
            )
        )
    with pytest.raises(EphemerisError, match="not found"):
        TabularSpacecraftObserverV1(
            Observer.spacecraft_table(
                "craft",
                str(tmp_path / "missing.ecsv"),
                checksum_sha256="sha256:unverifiable",
            )
        )


# ---------------------------------------------------------------------------
# SPICE spacecraft family
# ---------------------------------------------------------------------------


def make_spk(path: Path, target_id: int, base_et: float) -> None:
    """Write a small type-9 SPK: linear barycentric motion of a spacecraft."""
    spiceypy = pytest.importorskip("spiceypy")
    km_per_au = 149_597_870.700
    states = []
    epochs = []
    for k in range(10):
        et = base_et + k * 86_400.0
        position_au = np.array([0.5 + 0.01 * k, -0.7, -0.3])
        velocity_au_day = np.array([0.01, 0.0, 0.0])
        states.append(
            np.concatenate([position_au * km_per_au, velocity_au_day * km_per_au / 86_400.0])
        )
        epochs.append(et)
    handle = spiceypy.spkopn(str(path), "test-craft", 0)
    spiceypy.spkw09(
        handle,
        target_id,
        0,
        "J2000",
        epochs[0],
        epochs[-1],
        "test segment",
        1,  # polynomial degree 1: exact for linear motion
        len(states),
        states,
        epochs,
    )
    spiceypy.spkcls(handle)


def test_spice_spacecraft_provider(tmp_path: Path) -> None:
    pytest.importorskip("spiceypy")
    clear_provider_cache()
    base_et = (2459524.5 - 2451545.0) * 86_400.0  # 2021-11-06 00:00 TDB
    path = tmp_path / "craft.bsp"
    make_spk(path, -999, base_et)
    observer = Observer.spacecraft_spice(
        "craft", str(path), "-999", checksum_sha256=file_sha256(path)
    )
    provider = resolve_observer_state_provider(observer, EPHEMERIS)
    state = provider.state_at(Time(2459524.5 + 2.0, format="jd", scale="tdb"))
    assert state.position_au == pytest.approx((0.52, -0.7, -0.3), abs=1e-9)
    assert state.velocity_au_per_day == pytest.approx((0.01, 0.0, 0.0), abs=1e-12)
    assert provider.coverage.startswith("tdb_jd [2459524.5")
    with pytest.raises(EphemerisCoverageError, match="outside the SPICE coverage"):
        provider.state_at(Time(2459524.5 + 30.0, format="jd", scale="tdb"))
    assert np.allclose(
        observer_barycentric_au(
            observer, Time(2459524.5 + 2.0, format="jd", scale="tdb"), EPHEMERIS
        ),
        (0.52, -0.7, -0.3),
    )


def test_spice_unknown_target(tmp_path: Path) -> None:
    pytest.importorskip("spiceypy")
    path = tmp_path / "craft.bsp"
    make_spk(path, -999, 0.0)
    with pytest.raises(EphemerisError, match="no coverage for target"):
        resolve_observer_state_provider(
            Observer.spacecraft_spice("craft", str(path), "-42", checksum_sha256=file_sha256(path)),
            EPHEMERIS,
        )


# ---------------------------------------------------------------------------
# Programmatic family
# ---------------------------------------------------------------------------


def test_programmatic_observer_registration() -> None:
    clear_provider_cache()
    unregister_programmatic_observer("sim")
    observer = Observer.programmatic("sim", identity="sim-model-v1")
    with pytest.raises(GenerationError, match="no\\s+registered state function"):
        resolve_observer_state_provider(observer, EPHEMERIS)

    register_programmatic_observer(
        "sim", lambda time: np.array([1.0, 2.0, float(time.tdb.jyear > 2020.0)])
    )
    provider = resolve_observer_state_provider(observer, EPHEMERIS)
    assert isinstance(provider, ProgrammaticObserverV1)
    assert provider.state_at(T_O).position_au == (1.0, 2.0, 1.0)
    # Re-registration replaces the function (and drops the memoized provider).
    register_programmatic_observer("sim", lambda time: np.array([9.0, 9.0, 9.0]))
    provider = resolve_observer_state_provider(observer, EPHEMERIS)
    assert provider.state_at(T_O).position_au == (9.0, 9.0, 9.0)
    register_programmatic_observer("sim", lambda time: np.array([1.0, np.nan, 0.0]))
    with pytest.raises(GenerationError, match="invalid position"):
        resolve_observer_state_provider(observer, EPHEMERIS).state_at(T_O)
    unregister_programmatic_observer("sim")


# ---------------------------------------------------------------------------
# Request parsing and calculation-ID integration
# ---------------------------------------------------------------------------


def make_target(target_id: str = "synth") -> Target:
    return Target(
        target_id=target_id,
        display_name="Synthetic",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=10.0,
            dec_deg=20.0,
            pm_ra_cosdec_mas_per_yr=100.0,
            pm_dec_mas_per_yr=-50.0,
            reference_epoch_jyear=2016.0,
            reference_epoch_scale="tdb",
            source="unit test values",
            distance_pc=200_000.0 / AU_PER_PC,
            radial_velocity_km_s=0.0,
        ),
    )


def test_calculation_id_is_path_independent(tmp_path: Path) -> None:
    from sglseti.models import Role

    clear_provider_cache()
    registry = TargetRegistry.from_targets((make_target(),))
    first = write_table(
        tmp_path / "a.ecsv",
        [2459524.0, 2459534.0],
        [(0.5, -0.7, -0.3), (0.6, -0.7, -0.3)],
    )
    second = tmp_path / "elsewhere.ecsv"
    shutil.copyfile(first, second)

    def calc_id(path: Path) -> str:
        request = GeometryRequest(
            target_ids=("synth",),
            roles=(Role.RX,),
            time=TimeList(epochs=(Epoch(epoch_id="e1", time=T_O),)),
            observer=Observer.spacecraft_table(
                "craft", str(path), checksum_sha256=file_sha256(path)
            ),
            relay_range=RelayRange(550.0, 2500.0),
            sampling=SamplingSpec(kind=SamplingKind.COUNT, count=3),
            model_id="tusay2022_eq5_7_v1",
            output_formats=(OutputFormat.ECSV,),
        )
        return plan_calculation(request, registry, ephemeris=EPHEMERIS).calculation_id

    assert calc_id(first) == calc_id(second)  # identity from content, not path
    changed = write_table(
        tmp_path / "changed.ecsv",
        [2459524.0, 2459534.0],
        [(0.5, -0.7, -0.3), (0.7, -0.7, -0.3)],
    )
    assert calc_id(changed) != calc_id(first)
    # An earth-center request's canonical observer is untouched by all this:
    # covered by the frozen regression product fixtures.


def test_request_yaml_parses_new_observer_kinds(tmp_path: Path) -> None:
    base: dict[str, Any] = {
        "schema_version": 1,
        "targets": ["barnard"],
        "roles": ["rx"],
        "time": {"epoch_utc": "2021-11-06T03:14:00Z"},
        "relay_range": {
            "min_au": 550.0,
            "max_au": 2500.0,
            "sampling": {"kind": "count", "count": 5},
        },
        "model": {"id": "tusay2022_eq5_7_v1"},
    }
    cases: list[tuple[dict[str, Any], ObserverKind]] = [
        (
            {"kind": "solar_system_body", "name": "mars-observer", "body": "mars"},
            ObserverKind.SOLAR_SYSTEM_BODY,
        ),
        (
            {
                "kind": "spacecraft_table",
                "name": "wise",
                "path": "wise.ecsv",
                "checksum_sha256": "sha256:ab12",
            },
            ObserverKind.SPACECRAFT_TABLE,
        ),
        (
            {
                "kind": "spacecraft_spice",
                "name": "jwst",
                "path": "jwst.bsp",
                "spice_target": "-170",
                "checksum_sha256": "sha256:cd34",
            },
            ObserverKind.SPACECRAFT_SPICE,
        ),
        (
            {"kind": "programmatic", "name": "sim", "identity": "sim-v1"},
            ObserverKind.PROGRAMMATIC,
        ),
    ]
    for observer_block, kind in cases:
        data = dict(base, observer=observer_block)
        path = tmp_path / "request.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        request = load_request(path)
        assert request.observer.kind is kind
        assert request.observer.observer_id == observer_block["name"]
    bad = dict(base, observer={"kind": "spacecraft_table", "name": "wise"})  # missing path
    path = tmp_path / "request.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ConfigError, match="path"):
        load_request(path)


def test_stable_hash_distinguishes_new_observer_content() -> None:
    assert stable_hash(Observer.solar_system_body("mars")) != stable_hash(
        Observer.solar_system_body("jupiter")
    )


# ---------------------------------------------------------------------------
# Spacecraft crossing smoke (§3.3 composition through the provider layer)
# ---------------------------------------------------------------------------


def test_crossing_search_with_tabular_spacecraft_observer(tmp_path: Path) -> None:
    """A spacecraft observer drifts across a beam axis; crossings finds it."""
    import math as _math

    from sglseti.crossings import find_crossings
    from sglseti.models import CrossingsRequest, LinkDirection, TimeInterval, Validity

    clear_provider_cache()
    axis = np.array(
        [
            _math.cos(_math.radians(20.0)) * _math.cos(_math.radians(10.0)),
            _math.cos(_math.radians(20.0)) * _math.sin(_math.radians(10.0)),
            _math.sin(_math.radians(20.0)),
        ]
    )
    perp_1 = np.cross(axis, [0.0, 0.0, 1.0])
    perp_1 /= np.linalg.norm(perp_1)
    perp_2 = np.cross(axis, perp_1)
    perp_2 /= np.linalg.norm(perp_2)
    sun = np.array([0.004, -0.002, 0.001])
    base_jd = float(T_O.tdb.jd)
    # Pad the table 10 days past both scan boundaries: Time round-trips can
    # land an exact-boundary probe one ulp outside the tabulated span.
    epochs = [base_jd - 10.0 + 10.0 * k for k in range(14)]  # -10..+120 days
    velocity = -0.001 * perp_1
    positions = [
        tuple(sun + 5.0 * axis + (0.05 - 0.001 * (jd - base_jd)) * perp_1 + 0.02 * perp_2)
        for jd in epochs
    ]
    velocities = [tuple(velocity) for _ in epochs]
    table_path = write_table(tmp_path / "craft.ecsv", epochs, positions, velocities)
    target = make_target()
    # Zero proper motion keeps the axis fixed, as in the uncertainty tests.
    request = CrossingsRequest(
        target_ids=("synth",),
        link_directions=(LinkDirection.INBOUND,),
        intervals=(TimeInterval(interval_id="i1", start=T_O, stop=T_O + 100.0),),
        observer=Observer.spacecraft_table(
            "craft", str(table_path), checksum_sha256=file_sha256(table_path)
        ),
        relay_distance_au=1000.0,
        model_id="tusay2022_eq5_7_v1",
        coarse_step_days=10.0,
    )
    registry = TargetRegistry.from_targets((target,))
    result = find_crossings(request, registry, ephemeris=EPHEMERIS)
    events = [e for e in result.events if e.validity is not Validity.INVALID]
    assert len(events) == 1
    assert events[0].observer_id == "craft"
    assert events[0].b_min_au == pytest.approx(0.02, rel=0.05)
