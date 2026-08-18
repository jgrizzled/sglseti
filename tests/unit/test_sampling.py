from __future__ import annotations

import math
from pathlib import Path

import pytest

from sglseti.models import RelayRange, Role, SamplingKind, SamplingSpec
from sglseti.provenance import stable_hash
from sglseti.sampling import ARCSEC_PER_RADIAN, generate_segments, segments_for_request

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

RANGE = RelayRange(550.0, 2500.0)
COUNT_25 = SamplingSpec(kind=SamplingKind.COUNT, count=25)

# Golden identities: frozen so an accidental change to the ID payload or the
# canonical schema is loud. Never refresh without a documented reason.
GOLDEN_FIRST_SEGMENT_ID = "seg-15138ee11203"
GOLDEN_TABLE_HASH = "sha256:455e97259cc72721fa7d38f6b874a2a43fa133f2c1a76f5742802764f7b8c09c"


def barnard_rx(sampling: SamplingSpec = COUNT_25, relay_range: RelayRange = RANGE):
    return generate_segments(
        target_id="barnard", role=Role.RX, relay_range=relay_range, sampling=sampling
    )


def test_covers_range_without_gaps_or_overlap() -> None:
    segments = barnard_rx()
    assert len(segments) == 25
    # Exact bounds at the range endpoints, bit-for-bit.
    assert segments[0].z_near_au == RANGE.z_min_au
    assert segments[-1].z_far_au == RANGE.z_max_au
    # q-space continuity between neighbors.
    for left, right in zip(segments[:-1], segments[1:], strict=False):
        assert left.q_lo_per_au == right.q_hi_per_au
        assert abs(left.z_far_au - right.z_near_au) < 1e-9
    for segment in segments:
        assert segment.z_near_au < segment.z_rep_au < segment.z_far_au
        assert math.isclose(segment.q_lo_per_au, 1.0 / segment.z_far_au, rel_tol=1e-12)
        assert math.isclose(segment.q_hi_per_au, 1.0 / segment.z_near_au, rel_tol=1e-12)


def test_ordering_is_near_to_far_and_indexed() -> None:
    segments = barnard_rx()
    z_values = [segment.z_near_au for segment in segments]
    assert z_values == sorted(z_values)
    assert [segment.index for segment in segments] == list(range(25))


def test_uniform_in_reciprocal_distance() -> None:
    segments = barnard_rx()
    widths = [seg.q_hi_per_au - seg.q_lo_per_au for seg in segments]
    assert max(widths) - min(widths) < 1e-15


def test_single_segment_boundary() -> None:
    (segment,) = barnard_rx(SamplingSpec(kind=SamplingKind.COUNT, count=1))
    assert segment.z_near_au == RANGE.z_min_au
    assert segment.z_far_au == RANGE.z_max_au


def test_reciprocal_step_count_and_bound() -> None:
    step_arcsec = 15.0
    segments = barnard_rx(
        SamplingSpec(kind=SamplingKind.RECIPROCAL_STEP, step_arcsec=step_arcsec)
    )
    span = 1.0 / RANGE.z_min_au - 1.0 / RANGE.z_max_au
    step_q = step_arcsec / ARCSEC_PER_RADIAN
    assert len(segments) == max(1, math.ceil(span / step_q))
    # The actual angular step never exceeds the requested step.
    for segment in segments:
        assert (segment.q_hi_per_au - segment.q_lo_per_au) <= step_q * (1 + 1e-12)
    assert segments[0].z_near_au == RANGE.z_min_au
    assert segments[-1].z_far_au == RANGE.z_max_au


def test_explicit_distances_are_point_segments() -> None:
    distances = (550.0, 1000.0, 2500.0)
    segments = barnard_rx(
        SamplingSpec(kind=SamplingKind.EXPLICIT, distances_au=distances)
    )
    assert [segment.z_rep_au for segment in segments] == list(distances)
    for segment in segments:
        assert segment.is_point
        assert segment.z_near_au == segment.z_far_au == segment.z_rep_au


def test_deterministic_ids_across_runs() -> None:
    first = barnard_rx()
    second = barnard_rx()
    assert first == second
    assert [s.segment_id for s in first] == [s.segment_id for s in second]


def test_golden_identities() -> None:
    segments = barnard_rx()
    assert segments[0].segment_id == GOLDEN_FIRST_SEGMENT_ID
    assert stable_hash(segments) == GOLDEN_TABLE_HASH


@pytest.mark.parametrize(
    "variant",
    [
        {"target_id": "other"},
        {"role": Role.TX},
        {"relay_range": RelayRange(551.0, 2500.0)},
        {"sampling": SamplingSpec(kind=SamplingKind.COUNT, count=26)},
    ],
)
def test_every_scientific_change_changes_identity(variant: dict) -> None:
    base = dict(
        target_id="barnard", role=Role.RX, relay_range=RANGE, sampling=COUNT_25
    )
    changed = generate_segments(**{**base, **variant})
    assert stable_hash(changed) != stable_hash(barnard_rx())


def test_identity_is_date_independent() -> None:
    # Nothing time-like enters segment identity: the payload is target, role,
    # and physical bounds only. Guarded structurally via the golden ID above;
    # here we assert no field of the segment depends on a clock.
    segment = barnard_rx()[0]
    field_values = vars(segment)
    for value in field_values.values():
        assert not hasattr(value, "isot")


def test_unit_normalization_au_vs_km() -> None:
    from astropy import units as u

    in_au = RelayRange(550 * u.au, 2500 * u.au)
    in_km = RelayRange((550 * u.au).to(u.km), (2500 * u.au).to(u.km))
    assert stable_hash(barnard_rx(relay_range=in_au)) == stable_hash(
        barnard_rx(relay_range=in_km)
    )


def test_segments_for_request_ordering() -> None:
    from sglseti.config import load_request

    request = load_request(EXAMPLES / "historical.yaml")
    segments = segments_for_request(request)
    assert len(segments) == 25 * 2  # one target, roles rx and tx, count 25
    assert [s.role for s in segments[:25]] == [Role.RX] * 25
    assert [s.role for s in segments[25:]] == [Role.TX] * 25
    assert len({s.segment_id for s in segments}) == 50  # role in ID payload


def test_no_ephemeris_or_geometry_needed() -> None:
    # Exit criterion: sample tables and IDs generate without an ephemeris.
    import sys

    assert "sglseti.geometry" not in sys.modules
    assert "sglseti.ephemeris" not in sys.modules
    barnard_rx()
