from __future__ import annotations

from pathlib import Path

import pytest

from sglseti.config import load_epoch_table
from sglseti.errors import ConfigError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_example_ecsv_loads() -> None:
    epochs = load_epoch_table(EXAMPLES / "historical_epochs.ecsv")
    assert [epoch.epoch_id for epoch in epochs] == [
        "archive-exposure-1",
        "archive-exposure-2",
        "archive-exposure-3",
        "archive-exposure-4",
    ]
    assert epochs[0].metadata == {"dataset_id": "SURVEY-A-000123"}
    assert epochs[0].time.scale == "utc"
    assert epochs[0].time.isot.startswith("2012-06-01T05:30:00")


def test_csv_loads(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text(
        "epoch_id,time_utc,exposure_s\n"
        "e1,2020-01-01T00:00:00Z,300\n"
        "e2,2020-01-01T01:00:00+02:00,600\n",
        encoding="utf-8",
    )
    epochs = load_epoch_table(path)
    assert len(epochs) == 2
    assert epochs[0].metadata == {"exposure_s": "300"}
    # +02:00 offset is normalized to UTC.
    assert epochs[1].time.isot.startswith("2019-12-31T23:00:00")


def test_missing_required_column(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text("epoch_id,when\ne1,2020-01-01T00:00:00Z\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"missing required column\(s\) \['time_utc'\]"):
        load_epoch_table(path)


def test_duplicate_epoch_ids(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text(
        "epoch_id,time_utc\ne1,2020-01-01T00:00:00Z\ne1,2020-01-02T00:00:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate epoch_id 'e1'"):
        load_epoch_table(path)


def test_naive_timestamp_rejected(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text("epoch_id,time_utc\ne1,2020-01-01T00:00:00\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no UTC designator or offset"):
        load_epoch_table(path)


def test_invalid_timestamp_rejected(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text("epoch_id,time_utc\ne1,not-a-time\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid ISO-8601"):
        load_epoch_table(path)


def test_empty_table_rejected(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text("epoch_id,time_utc\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no rows"):
        load_epoch_table(path)


def test_empty_epoch_id_rejected(tmp_path: Path) -> None:
    path = tmp_path / "epochs.csv"
    path.write_text("epoch_id,time_utc\n,2020-01-01T00:00:00Z\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="epoch_id.*non-empty"):
        load_epoch_table(path)


def test_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "epochs.txt"
    path.write_text("epoch_id,time_utc\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unsupported epoch table format"):
        load_epoch_table(path)


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="file not found"):
        load_epoch_table("/nonexistent/epochs.ecsv")
