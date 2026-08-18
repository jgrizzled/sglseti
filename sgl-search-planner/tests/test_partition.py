from sgl_search.config import TargetSelection
from sgl_search.partition import generate_cells


def make_selection() -> TargetSelection:
    return TargetSelection(
        target_id="test",
        roles=("receiver",),
        min_au=550.0,
        max_au=2500.0,
        partition_kind="inverse_range",
        partition_step_arcsec=15.0,
        partition_cells=None,
        include_cells=(),
        exclude_cells=(),
    )


def test_partition_covers_reciprocal_range_without_gaps():
    selection = make_selection()
    cells = generate_cells(selection, "receiver")
    assert cells
    assert abs(cells[0].q_lo_per_au - 1 / selection.max_au) < 1e-15
    assert abs(cells[-1].q_hi_per_au - 1 / selection.min_au) < 1e-15
    for left, right in zip(cells[:-1], cells[1:]):
        assert abs(left.q_hi_per_au - right.q_lo_per_au) < 1e-15
    assert all(cell.z_near_au < cell.z_far_au for cell in cells)


def test_partition_ids_are_deterministic():
    a = generate_cells(make_selection(), "receiver")
    b = generate_cells(make_selection(), "receiver")
    assert [cell.cell_id for cell in a] == [cell.cell_id for cell in b]


def test_unknown_include_cell_fails_loudly():
    selection = TargetSelection(
        target_id="test",
        roles=("receiver",),
        min_au=550.0,
        max_au=2500.0,
        partition_kind="inverse_range",
        partition_step_arcsec=15.0,
        partition_cells=None,
        include_cells=("test.receiver.not-a-real-partition.0000",),
        exclude_cells=(),
    )
    import pytest

    with pytest.raises(ValueError, match="Unknown include_cells"):
        generate_cells(selection, "receiver")
