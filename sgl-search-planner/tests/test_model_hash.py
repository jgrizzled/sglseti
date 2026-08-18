from dataclasses import replace

from sgl_search.config import load_campaign, load_targets
from sgl_search.partition import all_cells
from sgl_search.planner import cell_model_hash


def test_corridor_width_changes_model_hash():
    targets = load_targets("examples/targets.yaml")
    campaign = load_campaign("examples/campaign.yaml")
    cell = all_cells(campaign.selections)[0]
    original = cell_model_hash(targets[cell.target_id], cell, campaign)
    wider_instrument = replace(
        campaign.instrument,
        corridor_half_width_arcsec=(
            campaign.instrument.corridor_half_width_arcsec + 1.0
        ),
    )
    wider = replace(campaign, instrument=wider_instrument)
    assert cell_model_hash(targets[cell.target_id], cell, wider) != original
