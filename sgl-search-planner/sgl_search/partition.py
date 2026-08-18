from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable

from .config import TargetSelection

ARCSEC_PER_RADIAN = 206264.80624709636


@dataclass(frozen=True)
class SearchCell:
    cell_id: str
    target_id: str
    role: str
    partition_id: str
    index: int
    q_lo_per_au: float
    q_hi_per_au: float
    z_near_au: float
    z_far_au: float

    @property
    def q_mid_per_au(self) -> float:
        return 0.5 * (self.q_lo_per_au + self.q_hi_per_au)

    @property
    def z_mid_au(self) -> float:
        return 1.0 / self.q_mid_per_au


def _partition_id(selection: TargetSelection) -> str:
    payload = {
        "kind": selection.partition_kind,
        "min_au": selection.min_au,
        "max_au": selection.max_au,
        "step_arcsec": selection.partition_step_arcsec,
        "cells": selection.partition_cells,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:10]


def generate_cells(selection: TargetSelection, role: str) -> list[SearchCell]:
    """Partition a heliocentric range into cells uniform in reciprocal distance.

    For a one-AU observer baseline, reciprocal distance q=1/z is approximately
    the parallax angle in radians. Uniform q cells therefore map much more
    naturally to fixed angular telescope fields than uniform-AU cells.
    """

    q_min = 1.0 / selection.max_au
    q_max = 1.0 / selection.min_au
    span = q_max - q_min
    if selection.partition_cells is not None:
        count = selection.partition_cells
    else:
        assert selection.partition_step_arcsec is not None
        step_rad = selection.partition_step_arcsec / ARCSEC_PER_RADIAN
        count = max(1, math.ceil(span / step_rad))

    partition_id = _partition_id(selection)
    edges = [q_min + span * i / count for i in range(count + 1)]
    cells: list[SearchCell] = []
    for index, (q_lo, q_hi) in enumerate(zip(edges[:-1], edges[1:])):
        cell_id = f"{selection.target_id}.{role}.{partition_id}.{index:04d}"
        cell = SearchCell(
            cell_id=cell_id,
            target_id=selection.target_id,
            role=role,
            partition_id=partition_id,
            index=index,
            q_lo_per_au=q_lo,
            q_hi_per_au=q_hi,
            z_near_au=1.0 / q_hi,
            z_far_au=1.0 / q_lo,
        )
        cells.append(cell)

    include = set(selection.include_cells)
    exclude = set(selection.exclude_cells)
    available = {cell.cell_id for cell in cells}
    unknown_include = include - available
    unknown_exclude = exclude - available
    if unknown_include:
        raise ValueError(
            f"Unknown include_cells for {selection.target_id}/{role}: "
            f"{sorted(unknown_include)}"
        )
    if unknown_exclude:
        raise ValueError(
            f"Unknown exclude_cells for {selection.target_id}/{role}: "
            f"{sorted(unknown_exclude)}"
        )
    if include:
        cells = [cell for cell in cells if cell.cell_id in include]
    if exclude:
        cells = [cell for cell in cells if cell.cell_id not in exclude]
    return cells


def all_cells(selections: Iterable[TargetSelection]) -> list[SearchCell]:
    cells: list[SearchCell] = []
    seen: set[str] = set()
    for selection in selections:
        for role in selection.roles:
            generated = generate_cells(selection, role)
            duplicates = sorted(cell.cell_id for cell in generated if cell.cell_id in seen)
            if duplicates:
                raise ValueError(
                    "Selections generate duplicate stable cell IDs: "
                    + ", ".join(duplicates[:5])
                    + (" ..." if len(duplicates) > 5 else "")
                )
            cells.extend(generated)
            seen.update(cell.cell_id for cell in generated)
    return cells
