"""End-to-end historical generation (UC1/UC4/UC5) on the shipped example.

Loads the real example registry, request, and ECSV epoch table, runs the
full batch through the astropy builtin ephemeris, and checks the archival
contract: every input epoch_id joins back losslessly, ordering is the
documented one, and the same engine handles past and future epochs in one
list.
"""

from __future__ import annotations

import time as time_module

import pytest
from support import EXAMPLES_DIR

from sglseti.config import load_request
from sglseti.generate import generate_loci
from sglseti.models import Role, TimeList, Validity
from sglseti.targets import load_target_registry


@pytest.fixture(scope="module")
def result_and_request():
    registry = load_target_registry(EXAMPLES_DIR / "targets.yaml")
    request = load_request(EXAMPLES_DIR / "historical.yaml")
    started = time_module.monotonic()
    result = generate_loci(request, registry)
    elapsed = time_module.monotonic() - started
    return result, request, elapsed


def test_shape_counts_and_validity(result_and_request) -> None:
    result, _, _ = result_and_request
    # 1 target x 2 roles x 4 epochs x 25 segments.
    assert len(result.samples) == 200
    assert len(result.corridors) == 8
    assert all(sample.validity is Validity.VALID for sample in result.samples)
    assert all(len(corridor.samples) == 25 for corridor in result.corridors)


def test_every_epoch_id_joins_back_losslessly(result_and_request) -> None:
    result, request, _ = result_and_request
    assert isinstance(request.time, TimeList)
    input_ids = [epoch.epoch_id for epoch in request.time.epochs]
    output_ids = {sample.epoch_id for sample in result.samples}
    assert output_ids == set(input_ids)
    # Every (role, epoch) group is complete — a join on epoch_id loses nothing.
    for epoch_id in input_ids:
        rows = [s for s in result.samples if s.epoch_id == epoch_id]
        assert len(rows) == 50  # 2 roles x 25 segments
    # Pass-through metadata rides on the request, keyed by epoch_id.
    metadata = {e.epoch_id: dict(e.metadata) for e in request.time.epochs}
    assert metadata["archive-exposure-3"] == {"dataset_id": "GBT-ALPHACEN-DEMO"}


def test_documented_output_order(result_and_request) -> None:
    result, request, _ = result_and_request
    assert isinstance(request.time, TimeList)
    epoch_order = [epoch.epoch_id for epoch in request.time.epochs]
    expected_keys = [
        (role, epoch_id)
        for role in (Role.RX, Role.TX)
        for epoch_id in epoch_order
    ]
    seen_keys = []
    for sample in result.samples:
        key = (sample.role, sample.epoch_id)
        if not seen_keys or seen_keys[-1] != key:
            seen_keys.append(key)
    assert seen_keys == expected_keys
    for corridor in result.corridors:
        z_values = [sample.z_au for sample in corridor.samples]
        assert z_values == sorted(z_values)


def test_epoch_neutrality_past_and_future_in_one_list(result_and_request) -> None:
    result, _, _ = result_and_request
    # The example spans 2012-2024; all handled identically by one engine.
    times = sorted({sample.observation_time_utc for sample in result.samples})
    assert times[0].startswith("2012-06-01")
    assert times[-1].startswith("2024-01-20")


def test_rows_carry_full_scientific_metadata(result_and_request) -> None:
    result, _, _ = result_and_request
    sample = result.samples[0]
    assert sample.calculation_id == result.calculation_id
    assert sample.model_id == "tusay2022_eq5_7_v1"
    assert sample.model_version == "1.1.0"
    assert sample.ephemeris_id == "astropy_builtin"
    assert sample.target_source_hash.startswith("sha256:")
    assert sample.observer_id == "example-kitt-peak"
    assert sample.catalog_epoch_semantics == "ssb_light_arrival_time"
    # Rx catalog epoch precedes observation; physical emission precedes both.
    rx = next(s for s in result.samples if s.role is Role.RX)
    assert rx.catalog_direction_epoch_tdb_jd < rx.observation_time_tdb_jd
    assert rx.target_event_epoch_tdb_jd_approx < rx.catalog_direction_epoch_tdb_jd
    tx = next(s for s in result.samples if s.role is Role.TX)
    assert tx.catalog_direction_epoch_tdb_jd > tx.observation_time_tdb_jd


def test_no_coverage_or_completion_language(result_and_request) -> None:
    result, _, _ = result_and_request
    for warning in result.warnings:
        assert "covered" not in warning and "complete" not in warning


def test_representative_batch_is_interactive(result_and_request) -> None:
    _, _, elapsed = result_and_request
    # 200 samples through the real astropy path; generous CI bound.
    assert elapsed < 60.0


def test_reruns_are_identical(result_and_request) -> None:
    result, request, _ = result_and_request
    registry = load_target_registry(EXAMPLES_DIR / "targets.yaml")
    again = generate_loci(request, registry)
    assert again.calculation_id == result.calculation_id
    assert again.samples == result.samples
    assert again.corridors == result.corridors
