from __future__ import annotations

import pytest
from support import make_locus_sample

from sglseti.planning import group_corridor_samples


def line_samples(
    count: int,
    spacing_arcsec: float,
    *,
    rates: tuple[float, float] | None = None,
) -> tuple:
    """Samples along the equator at RA offsets of ``spacing_arcsec``."""
    samples = []
    for index in range(count):
        overrides: dict = dict(
            sample_id=f"smp-{index:03d}",
            icrs_ra_deg=index * spacing_arcsec / 3600.0,
            icrs_dec_deg=0.0,
            z_au=550.0 + index,
        )
        if rates is not None:
            overrides["rate_ra_cosdec_arcsec_per_hr"] = rates[0]
            overrides["rate_dec_arcsec_per_hr"] = rates[1]
        samples.append(make_locus_sample(**overrides))
    return tuple(samples)


def test_greedy_adjacent_grouping_sizes() -> None:
    # Spacing 30", half-width 10", usable 50": a group spanning three samples
    # has extent 30 -> radius 40 (fits); four samples extent 45 -> 55 (no).
    samples = line_samples(7, 30.0)
    groups = group_corridor_samples(
        samples,
        usable_radius_arcsec=50.0,
        assumed_half_width_arcsec=10.0,
        exposure_s=None,
    )
    assert [len(group) for group, _ in groups] == [3, 3, 1]
    # Adjacency and order preserved: concatenation reproduces the corridor.
    flattened = [sample for group, _ in groups for sample in group]
    assert [s.sample_id for s in flattened] == [s.sample_id for s in samples]


def test_zone_geometry_components() -> None:
    samples = line_samples(3, 30.0)
    ((group, zone),) = group_corridor_samples(
        samples,
        usable_radius_arcsec=100.0,
        assumed_half_width_arcsec=10.0,
        exposure_s=None,
    )
    assert len(group) == 3
    # Center at the middle of the endpoints (RA 30" of 0..60"), extent 30".
    assert zone.center_ra_deg * 3600.0 == pytest.approx(30.0, abs=1e-6)
    assert zone.center_dec_deg == pytest.approx(0.0, abs=1e-9)
    assert zone.track_extent_arcsec == pytest.approx(30.0, abs=1e-6)
    assert zone.motion_padding_arcsec == 0.0
    assert zone.radius_arcsec == pytest.approx(40.0, abs=1e-6)


def test_motion_padding_component() -> None:
    # 12 arcsec/hr total rate, 600 s exposure: padding = 12 * (1/6) / 2 = 1".
    samples = line_samples(2, 30.0, rates=(12.0, 0.0))
    ((_, zone),) = group_corridor_samples(
        samples,
        usable_radius_arcsec=100.0,
        assumed_half_width_arcsec=None,
        exposure_s=600.0,
    )
    assert zone.motion_padding_arcsec == pytest.approx(1.0, abs=1e-9)
    assert zone.radius_arcsec == pytest.approx(15.0 + 1.0, abs=1e-6)


def test_padding_uses_fastest_group_member() -> None:
    fast = make_locus_sample(
        sample_id="smp-fast",
        icrs_ra_deg=0.0,
        rate_ra_cosdec_arcsec_per_hr=3.0,
        rate_dec_arcsec_per_hr=4.0,  # total 5 arcsec/hr
    )
    slow = make_locus_sample(
        sample_id="smp-slow",
        icrs_ra_deg=10.0 / 3600.0,
        rate_ra_cosdec_arcsec_per_hr=1.0,
        rate_dec_arcsec_per_hr=0.0,
    )
    ((_, zone),) = group_corridor_samples(
        (fast, slow),
        usable_radius_arcsec=100.0,
        assumed_half_width_arcsec=None,
        exposure_s=3600.0,
    )
    assert zone.motion_padding_arcsec == pytest.approx(2.5, abs=1e-9)


def test_oversize_single_segment_becomes_singleton_zone() -> None:
    # Half-width alone exceeds the usable radius: nothing can merge, and
    # every zone honestly reports a radius larger than the field.
    samples = line_samples(3, 30.0)
    groups = group_corridor_samples(
        samples,
        usable_radius_arcsec=50.0,
        assumed_half_width_arcsec=100.0,
        exposure_s=None,
    )
    assert [len(group) for group, _ in groups] == [1, 1, 1]
    for _, zone in groups:
        assert zone.radius_arcsec > 50.0


def test_all_samples_grouped_exactly_once() -> None:
    samples = line_samples(11, 45.0)
    groups = group_corridor_samples(
        samples,
        usable_radius_arcsec=60.0,
        assumed_half_width_arcsec=5.0,
        exposure_s=None,
    )
    grouped_ids = [s.sample_id for group, _ in groups for s in group]
    assert grouped_ids == [s.sample_id for s in samples]
