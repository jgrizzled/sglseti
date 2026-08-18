from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    model_hash TEXT NOT NULL,
    target_id TEXT NOT NULL,
    role TEXT NOT NULL,
    observed_start_utc TEXT NOT NULL,
    observed_end_utc TEXT NOT NULL,
    telescope_id TEXT NOT NULL,
    band TEXT NOT NULL,
    signal_class TEXT NOT NULL,
    status TEXT NOT NULL,
    quality REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_cell_profile
    ON observations(cell_id, profile_id, model_hash, status, quality);
CREATE INDEX IF NOT EXISTS idx_observations_campaign
    ON observations(campaign_id, tile_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_observation_identity
    ON observations(campaign_id, tile_id, cell_id, profile_id, model_hash, observed_start_utc);
"""


@dataclass(frozen=True)
class ObservationRecord:
    campaign_id: str
    tile_id: str
    cell_id: str
    profile_id: str
    model_hash: str
    target_id: str
    role: str
    observed_start_utc: str
    observed_end_utc: str
    telescope_id: str
    band: str
    signal_class: str
    status: str
    quality: float
    notes: str = ""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def insert_observations(
    path: str | Path, records: Iterable[ObservationRecord]
) -> int:
    records = list(records)
    if not records:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as conn:
        conn.executemany(
            """
            INSERT INTO observations (
                campaign_id, tile_id, cell_id, profile_id, model_hash,
                target_id, role, observed_start_utc, observed_end_utc,
                telescope_id, band, signal_class, status, quality, notes, created_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, tile_id, cell_id, profile_id, model_hash, observed_start_utc)
            DO UPDATE SET
                observed_end_utc=excluded.observed_end_utc,
                telescope_id=excluded.telescope_id,
                band=excluded.band,
                signal_class=excluded.signal_class,
                status=excluded.status,
                quality=excluded.quality,
                notes=excluded.notes,
                created_utc=excluded.created_utc
            """,
            [
                (
                    r.campaign_id,
                    r.tile_id,
                    r.cell_id,
                    r.profile_id,
                    r.model_hash,
                    r.target_id,
                    r.role,
                    r.observed_start_utc,
                    r.observed_end_utc,
                    r.telescope_id,
                    r.band,
                    r.signal_class,
                    r.status,
                    float(r.quality),
                    r.notes,
                    now,
                )
                for r in records
            ],
        )
    return len(records)


def successful_visit_times(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    profile_id: str,
    model_hash: str,
    min_quality: float,
) -> list[datetime]:
    rows = conn.execute(
        """
        SELECT observed_start_utc
        FROM observations
        WHERE cell_id = ? AND profile_id = ? AND model_hash = ?
          AND status = 'success' AND quality >= ?
        ORDER BY observed_start_utc
        """,
        (cell_id, profile_id, model_hash, min_quality),
    ).fetchall()
    return [_parse_utc(str(row["observed_start_utc"])) for row in rows]


def independent_visit_count(times: Iterable[datetime], min_separation_days: float) -> int:
    sorted_times = sorted(times)
    if not sorted_times:
        return 0
    count = 0
    last_counted: datetime | None = None
    min_seconds = min_separation_days * 86400.0
    for current in sorted_times:
        if last_counted is None or (current - last_counted).total_seconds() >= min_seconds:
            count += 1
            last_counted = current
    return count


def cell_is_complete(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    profile_id: str,
    model_hash: str,
    min_quality: float,
    required_visits: int,
    min_visit_separation_days: float,
) -> bool:
    times = successful_visit_times(
        conn,
        cell_id=cell_id,
        profile_id=profile_id,
        model_hash=model_hash,
        min_quality=min_quality,
    )
    return (
        independent_visit_count(times, min_visit_separation_days)
        >= required_visits
    )


def summary(path: str | Path, profile_id: str | None = None) -> list[sqlite3.Row]:
    with connect(path) as conn:
        if profile_id:
            return conn.execute(
                """
                SELECT target_id, role, profile_id,
                       COUNT(DISTINCT cell_id) AS distinct_cells,
                       COUNT(*) AS observation_rows,
                       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS successes
                FROM observations
                WHERE profile_id = ?
                GROUP BY target_id, role, profile_id
                ORDER BY target_id, role
                """,
                (profile_id,),
            ).fetchall()
        return conn.execute(
            """
            SELECT target_id, role, profile_id,
                   COUNT(DISTINCT cell_id) AS distinct_cells,
                   COUNT(*) AS observation_rows,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS successes
            FROM observations
            GROUP BY target_id, role, profile_id
            ORDER BY profile_id, target_id, role
            """
        ).fetchall()
