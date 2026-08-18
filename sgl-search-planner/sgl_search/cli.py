from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from .catalog import CatalogError, simbad_target_yaml
from .config import ConfigError, load_campaign, load_targets
from .geometry import GeometryDependencyError
from .ledger import (
    ObservationRecord,
    cell_is_complete,
    connect,
    insert_observations,
    summary,
)
from .output import write_all
from .planner import cell_model_hash, plan
from .partition import all_cells



def _cmd_cells(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    cells = all_cells(campaign.selections)
    print("cell_id\ttarget_id\trole\tz_near_au\tz_far_au")
    for cell in cells:
        print(
            f"{cell.cell_id}\t{cell.target_id}\t{cell.role}\t"
            f"{cell.z_near_au:.6f}\t{cell.z_far_au:.6f}"
        )
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets)
    campaign = load_campaign(args.campaign)
    cells = all_cells(campaign.selections)
    unknown = sorted({cell.target_id for cell in cells} - set(targets))
    if unknown:
        raise ValueError(f"Campaign references unknown target IDs: {unknown}")
    complete_count = 0
    with connect(args.ledger) as conn:
        print("status\tcell_id\ttarget_id\trole\tz_near_au\tz_far_au")
        for cell in cells:
            model_hash = cell_model_hash(targets[cell.target_id], cell, campaign)
            complete = cell_is_complete(
                conn,
                cell_id=cell.cell_id,
                profile_id=campaign.profile.profile_id,
                model_hash=model_hash,
                min_quality=campaign.profile.min_quality,
                required_visits=campaign.profile.required_successful_visits,
                min_visit_separation_days=campaign.profile.min_visit_separation_days,
            )
            complete_count += int(complete)
            status = "complete" if complete else "missing"
            print(
                f"{status}\t{cell.cell_id}\t{cell.target_id}\t{cell.role}\t"
                f"{cell.z_near_au:.6f}\t{cell.z_far_au:.6f}"
            )
    print(
        f"# {complete_count}/{len(cells)} cells complete for profile "
        f"{campaign.profile.profile_id}",
        file=sys.stderr,
    )
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets)
    campaign = load_campaign(args.campaign)
    result = plan(targets, campaign, args.ledger)
    files = write_all(args.output_dir, result)
    print(
        f"Generated {len(result.tiles)} pointings from {result.remaining_cells} remaining "
        f"cells; {result.completed_cells}/{result.total_cells} cells were already complete."
    )
    for label, path in files.items():
        print(f"{label}: {path}")
    if result.invisible_groups:
        print(
            f"Skipped {result.invisible_groups} target/role groups that failed night constraints."
        )
    return 0


def _read_plan_rows(path: str | Path) -> dict[str, dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return {row["tile_id"]: row for row in csv.DictReader(handle)}


def _parse_result_utc(value: str, *, field: str, tile_id: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field} for {tile_id}: {value!r}; use ISO 8601 UTC."
        ) from exc
    if parsed.tzinfo is None:
        # Campaign timestamps are UTC by contract; do not inherit the host timezone.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cmd_ingest(args: argparse.Namespace) -> int:
    plan_rows = _read_plan_rows(args.plan)
    records: list[ObservationRecord] = []
    with Path(args.results).open(newline="", encoding="utf-8") as handle:
        for result in csv.DictReader(handle):
            tile_id = result.get("tile_id", "").strip()
            status = result.get("status", "").strip().lower()
            if not tile_id or not status:
                continue
            if tile_id not in plan_rows:
                raise ValueError(f"Results reference unknown tile_id {tile_id!r}.")
            if status not in {"success", "failed", "partial", "aborted"}:
                raise ValueError(
                    f"Invalid status {status!r} for {tile_id}; use success, failed, partial, or aborted."
                )
            row = plan_rows[tile_id]
            start = result.get("observed_start_utc", "").strip()
            end = result.get("observed_end_utc", "").strip()
            if not start:
                raise ValueError(f"Missing observed_start_utc for completed result {tile_id}.")
            start_dt = _parse_result_utc(
                start, field="observed_start_utc", tile_id=tile_id
            )
            if not end:
                end_dt = start_dt + timedelta(seconds=float(row["exposure_seconds"]))
            else:
                end_dt = _parse_result_utc(
                    end, field="observed_end_utc", tile_id=tile_id
                )
            if end_dt <= start_dt:
                raise ValueError(f"Observation end must follow start for {tile_id}.")
            start = start_dt.isoformat().replace("+00:00", "Z")
            end = end_dt.isoformat().replace("+00:00", "Z")
            quality = float(result.get("quality", "1.0") or 1.0)
            if not 0 <= quality <= 1:
                raise ValueError(f"Quality for {tile_id} must be in [0, 1].")
            notes = result.get("notes", "")
            cell_ids = row["cell_ids"].split(";")
            model_hashes = row["cell_model_hashes"].split(";")
            if len(cell_ids) != len(model_hashes):
                raise ValueError(f"Malformed cell/hash lists in plan row {tile_id}.")
            for cell_id, model_hash in zip(cell_ids, model_hashes):
                records.append(
                    ObservationRecord(
                        campaign_id=row["campaign_id"],
                        tile_id=tile_id,
                        cell_id=cell_id,
                        profile_id=row["profile_id"],
                        model_hash=model_hash,
                        target_id=row["target_id"],
                        role=row["role"],
                        observed_start_utc=start,
                        observed_end_utc=end,
                        telescope_id=row["telescope_id"],
                        band=row["band"],
                        signal_class=row["signal_class"],
                        status=status,
                        quality=quality,
                        notes=notes,
                    )
                )
    count = insert_observations(args.ledger, records)
    print(f"Inserted {count} cell-observation rows into {args.ledger}.")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    rows = summary(args.ledger, args.profile)
    if not rows:
        print("No observations recorded.")
        return 0
    print("target_id\trole\tprofile_id\tdistinct_cells\trows\tsuccesses")
    for row in rows:
        print(
            f"{row['target_id']}\t{row['role']}\t{row['profile_id']}\t"
            f"{row['distinct_cells']}\t{row['observation_rows']}\t{row['successes']}"
        )
    return 0


def _cmd_simbad(args: argparse.Namespace) -> int:
    print(simbad_target_yaml(args.name, args.target_id), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sgl-search",
        description="Targeted pointing planner and ledger for SGL technosignature searches.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_cells = sub.add_parser("cells", help="List stable physical search-cell IDs.")
    p_cells.add_argument("--campaign", required=True, help="Campaign YAML defining partitions.")
    p_cells.set_defaults(func=_cmd_cells)

    p_coverage = sub.add_parser("coverage", help="List complete and missing cells for a profile.")
    p_coverage.add_argument("--targets", required=True)
    p_coverage.add_argument("--campaign", required=True)
    p_coverage.add_argument("--ledger", required=True)
    p_coverage.set_defaults(func=_cmd_coverage)

    p_plan = sub.add_parser("plan", help="Create unobserved pointing zones for one night.")
    p_plan.add_argument("--targets", required=True, help="Curated target registry YAML.")
    p_plan.add_argument("--campaign", required=True, help="Night/campaign YAML.")
    p_plan.add_argument("--ledger", required=True, help="SQLite observation ledger.")
    p_plan.add_argument("--output-dir", required=True, help="Directory for CSV/DS9 outputs.")
    p_plan.set_defaults(func=_cmd_plan)

    p_ingest = sub.add_parser("ingest", help="Ingest completed observation results.")
    p_ingest.add_argument("--plan", required=True, help="pointings.csv produced by plan.")
    p_ingest.add_argument("--results", required=True, help="Filled observation results CSV.")
    p_ingest.add_argument("--ledger", required=True, help="SQLite observation ledger.")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_report = sub.add_parser("report", help="Summarize ledger contents.")
    p_report.add_argument("--ledger", required=True)
    p_report.add_argument("--profile", help="Optional profile_id filter.")
    p_report.set_defaults(func=_cmd_report)

    p_simbad = sub.add_parser(
        "simbad", help="Resolve one explicitly named SIMBAD object and print YAML."
    )
    p_simbad.add_argument("--name", required=True)
    p_simbad.add_argument("--target-id", required=True)
    p_simbad.set_defaults(func=_cmd_simbad)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, GeometryDependencyError, CatalogError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
