"""Validity gating of observing products.

Finding 1: ``validity`` — not coordinate finiteness — is the authoritative
gate; a finite-coordinate ``invalid`` sample must never enter visibility,
pointings, or DS9 regions. Finding 6 then narrowed what ``invalid`` means:
the paper's ``z > d/10`` probe-placement restriction is a search prior, so
samples beyond it are ``degraded`` with ``outside_search_prior`` — they
remain consumable, and any pointing built from them carries the code so the
condition is visible without joining back to the samples table. ``invalid``
is reserved for uninterpretable results (e.g. ephemeris out of coverage),
and the finding-1 gate still enforces it everywhere.

Scenario: a synthetic target at 16,000 AU (prior bound at 1,600 AU) with a
relay range whose last representative sample lands near 1,927 AU.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from astropy.time import Time
from support import FakeEphemeris, build_small_result, make_locus_sample

from sglseti.export import write_products
from sglseti.geometry import WARN_OUTSIDE_SEARCH_PRIOR
from sglseti.models import (
    Epoch,
    ObservabilityConstraints,
    Observer,
    RelayRange,
    SamplingKind,
    SamplingSpec,
    Validity,
)
from sglseti.observability import visibility_sample

TARGET_DISTANCE_AU = 16_000.0
Z_PRIOR_BOUND_AU = TARGET_DISTANCE_AU / 10.0


@pytest.fixture(scope="module")
def planned():
    return build_small_result(
        planned=True,
        target_distance_au=TARGET_DISTANCE_AU,
        relay_range=RelayRange(550.0, 3000.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=4),
    )


@pytest.fixture(scope="module")
def outside_prior_ids(planned) -> set[str]:
    return {s.sample_id for s in planned.samples if WARN_OUTSIDE_SEARCH_PRIOR in s.warnings}


def test_beyond_prior_samples_are_degraded_and_operational(planned) -> None:
    flagged = [s for s in planned.samples if WARN_OUTSIDE_SEARCH_PRIOR in s.warnings]
    assert flagged  # the beyond-bound segment of each corridor
    for sample in flagged:
        assert sample.z_au > Z_PRIOR_BOUND_AU
        # Finding 6: outside the study's search prior is degraded — the
        # equations remain evaluable — never invalid.
        assert sample.validity is Validity.DEGRADED
        assert math.isfinite(sample.icrs_ra_deg)
        assert sample.is_operational


def test_no_sample_is_invalid_for_a_mere_prior_violation(planned) -> None:
    assert not any(s.validity is Validity.INVALID for s in planned.samples)


def test_pointings_using_prior_violating_samples_carry_the_code(planned, outside_prior_ids) -> None:
    assert planned.pointings
    flagged_pointings = [p for p in planned.pointings if outside_prior_ids & set(p.sample_ids)]
    assert flagged_pointings  # the samples are consumable, visibly
    for pointing in flagged_pointings:
        assert WARN_OUTSIDE_SEARCH_PRIOR in pointing.warnings
    for pointing in planned.pointings:
        if not outside_prior_ids & set(pointing.sample_ids):
            assert WARN_OUTSIDE_SEARCH_PRIOR not in pointing.warnings


def test_visibility_rejects_invalid_sample_with_finite_coordinates() -> None:
    # The finding-1 gate: validity, not finiteness, decides.
    sample = make_locus_sample(validity=Validity.INVALID)
    assert math.isfinite(sample.icrs_ra_deg)
    result = visibility_sample(
        sample=sample,
        epoch=Epoch(epoch_id="e1", time=Time("2021-11-06T00:00:00", scale="utc")),
        observer=Observer.from_geodetic("test-site", -111.6003, 31.9583, 2096.0),
        ephemeris=FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323)),
        constraints=ObservabilityConstraints(
            min_target_altitude_deg=-90.0,
            max_sun_altitude_deg=90.0,
            min_moon_separation_deg=0.0,
        ),
    )
    assert result.constraints_passed is False
    assert result.failed_constraints == ("sample_invalid",)


def test_invalid_rows_stay_out_of_products_but_in_tables(tmp_path: Path) -> None:
    # Ephemeris-coverage failure is the remaining (true) invalidity: its
    # rows are excluded from DS9 but preserved, labeled, in the JSON table.
    limited = FakeEphemeris(
        (0.004, -0.002, 0.001),
        (0.558, -0.744, -0.323),
        coverage_jd=(2459000.0, 2459600.0),  # excludes epoch e2
    )
    result = build_small_result(ephemeris=limited)
    invalid = [s for s in result.samples if s.validity is Validity.INVALID]
    assert invalid
    assert all(not s.is_operational for s in invalid)
    written = write_products(result, tmp_path, generated_utc="2026-08-17T12:00:00+00:00")
    assert "invalid sample(s) omitted" in written["regions_ds9"].read_text(encoding="utf-8")
    document = json.loads(written["result_json"].read_text(encoding="utf-8"))
    rows = [s for s in document["samples"] if s["validity"] == "invalid"]
    assert len(rows) == len(invalid)


def test_degraded_prior_rows_are_present_in_ds9(planned, outside_prior_ids, tmp_path: Path) -> None:
    written = write_products(planned, tmp_path, generated_utc="2026-08-17T12:00:00+00:00")
    ds9 = written["regions_ds9"].read_text(encoding="utf-8")
    for sample_id in outside_prior_ids:
        assert sample_id in ds9  # consumable, so exported
