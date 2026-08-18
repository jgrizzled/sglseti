"""Reciprocal-distance relay-range sampling.

A relay range [z_min, z_max] is partitioned uniformly in reciprocal distance
q = 1/z. For a one-AU observer baseline, q is approximately the relay's
parallax angle in radians, so uniform-q segments map naturally to fixed
angular telescope fields (ported from the prototype's ``partition.py``;
coverage/completion semantics removed per the implementation plan).

Ordering is deterministic: ascending z (nearest segment first), with the
first ``z_near_au`` exactly equal to the range minimum and the last
``z_far_au`` exactly equal to the range maximum. Segment identity depends
only on target, role, and physical bounds — never on the calendar date.

This module needs no ephemeris and no astropy import.
"""

from __future__ import annotations

import math

from .models import (
    GeometryRequest,
    RangeSegment,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
)
from .provenance import stable_id

__all__ = [
    "ARCSEC_PER_RADIAN",
    "generate_segments",
    "segments_for_request",
]

ARCSEC_PER_RADIAN = 648_000 / math.pi  # 206264.80624709636


def _segment_id(target_id: str, role: Role, z_near_au: float, z_far_au: float) -> str:
    return stable_id(
        "seg",
        {
            "target_id": target_id,
            "role": role,
            "z_near_au": z_near_au,
            "z_far_au": z_far_au,
        },
    )


def generate_segments(
    *,
    target_id: str,
    role: Role,
    relay_range: RelayRange,
    sampling: SamplingSpec,
) -> tuple[RangeSegment, ...]:
    """Partition ``relay_range`` for one target/role into ordered segments.

    - ``count``: exactly that many segments, uniform in q.
    - ``reciprocal_step``: enough uniform-q segments that each spans at most
      ``step_arcsec`` of reciprocal distance (ceil division, so the actual
      step never exceeds the requested one).
    - ``explicit``: zero-width point segments at the given distances.
    """
    if sampling.kind is SamplingKind.EXPLICIT:
        assert sampling.distances_au is not None
        segments = []
        for index, z_au in enumerate(sampling.distances_au):
            q = 1.0 / z_au
            segments.append(
                RangeSegment(
                    segment_id=_segment_id(target_id, role, z_au, z_au),
                    target_id=target_id,
                    role=role,
                    index=index,
                    z_near_au=z_au,
                    z_far_au=z_au,
                    q_lo_per_au=q,
                    q_hi_per_au=q,
                    z_rep_au=z_au,
                    is_point=True,
                )
            )
        return tuple(segments)

    z_min, z_max = relay_range.z_min_au, relay_range.z_max_au
    q_min = 1.0 / z_max
    q_max = 1.0 / z_min
    span = q_max - q_min
    if sampling.kind is SamplingKind.COUNT:
        assert sampling.count is not None
        count = sampling.count
    else:
        assert sampling.step_arcsec is not None
        step_q = sampling.step_arcsec / ARCSEC_PER_RADIAN
        count = max(1, math.ceil(span / step_q))

    # q edges descending so z ascends; z bounds forced exact at the range
    # endpoints so corridor limits equal the requested range bit-for-bit.
    q_edges = [q_max - span * k / count for k in range(count + 1)]
    q_edges[0] = q_max
    q_edges[count] = q_min
    segments = []
    for index in range(count):
        q_hi = q_edges[index]
        q_lo = q_edges[index + 1]
        z_near = z_min if index == 0 else 1.0 / q_hi
        z_far = z_max if index == count - 1 else 1.0 / q_lo
        z_rep = 2.0 / (q_hi + q_lo)
        segments.append(
            RangeSegment(
                segment_id=_segment_id(target_id, role, z_near, z_far),
                target_id=target_id,
                role=role,
                index=index,
                z_near_au=z_near,
                z_far_au=z_far,
                q_lo_per_au=q_lo,
                q_hi_per_au=q_hi,
                z_rep_au=z_rep,
            )
        )
    return tuple(segments)


def segments_for_request(request: GeometryRequest) -> tuple[RangeSegment, ...]:
    """All segments of a request, ordered by target, then role, then index.

    Target and role order follow the request (already validated unique).
    """
    segments: list[RangeSegment] = []
    for target_id in request.target_ids:
        for role in request.roles:
            segments.extend(
                generate_segments(
                    target_id=target_id,
                    role=role,
                    relay_range=request.relay_range,
                    sampling=request.sampling,
                )
            )
    return tuple(segments)
