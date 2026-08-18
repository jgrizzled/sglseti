from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

import sglseti
from sglseti.cli import build_parser, main
from sglseti.errors import ConfigError, SglsetiError


def test_version_matches_installed_metadata() -> None:
    assert sglseti.__version__ == importlib.metadata.version("sglseti")


def test_bare_invocation_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "sglseti" in out


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_version_flag_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert sglseti.__version__ in capsys.readouterr().out


def test_help_mentions_product_boundary() -> None:
    help_text = build_parser().format_help()
    for term in ("archive lookup", "coverage"):
        assert term in help_text


def test_no_ledger_commands_or_options() -> None:
    # The epilog may *disclaim* ledger workflows, but no command or option
    # may offer one.
    parser = build_parser()
    surface = parser.format_usage().lower()
    for action in parser._actions:
        surface += " ".join(action.option_strings).lower()
        if action.choices:
            surface += " ".join(str(choice) for choice in action.choices).lower()
    for term in ("ledger", "ingest", "coverage", "sqlite", "candidate"):
        assert term not in surface


def test_domain_errors_exit_with_status_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _failing_command(args: object) -> int:
        raise ConfigError("bad input file")

    def _parser_with_failing_command() -> object:
        parser = build_parser()
        parser.set_defaults(func=_failing_command)
        return parser

    monkeypatch.setattr("sglseti.cli.build_parser", _parser_with_failing_command)
    assert main([]) == 2
    assert "error: bad input file" in capsys.readouterr().err


def test_config_error_is_a_domain_error() -> None:
    assert issubclass(ConfigError, SglsetiError)


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_validate_targets_example(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "targets", str(EXAMPLES / "targets.yaml")]) == 0
    out = capsys.readouterr().out
    assert "OK: 1 target(s)" in out
    assert "barnard" in out
    assert "sha256:" in out


def test_validate_request_examples(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "request", str(EXAMPLES / "historical.yaml")]) == 0
    assert "4 listed epoch(s)" in capsys.readouterr().out
    assert main(["validate", "request", str(EXAMPLES / "commensal-night.yaml")]) == 0
    assert "grid at 600 s cadence" in capsys.readouterr().out


def test_validate_targets_invalid_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "targets.yaml"
    bad.write_text("schema_version: 2\ntargets: {}\n", encoding="utf-8")
    assert main(["validate", "targets", str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert str(bad) in err


def test_samples_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["samples", "--request", str(EXAMPLES / "historical.yaml")]) == 0
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert lines[0].startswith("segment_id\ttarget_id\trole")
    assert len(lines) == 1 + 50  # header + 25 segments x 2 roles
    first = lines[1].split("\t")
    assert first[1] == "barnard"
    assert first[2] == "rx"
    assert first[3] == "550.000000"
    assert "# 50 segment(s)" in captured.err


def test_samples_command_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    main(["samples", "--request", str(EXAMPLES / "historical.yaml")])
    first = capsys.readouterr().out
    main(["samples", "--request", str(EXAMPLES / "historical.yaml")])
    assert capsys.readouterr().out == first


def test_samples_invalid_request_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "request.yaml"
    bad.write_text("schema_version: 1\n", encoding="utf-8")
    assert main(["samples", "--request", str(bad)]) == 2
    assert "error: " in capsys.readouterr().err


def test_validate_targets_allow_missing_rv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = tmp_path / "targets.yaml"
    registry.write_text(
        """
schema_version: 2
targets:
  test-star:
    endpoint_kind: star
    state:
      provider: linear_astrometry_v1
      astrometry:
        frame: icrs
        ra_deg: 10.0
        dec_deg: 10.0
        parallax_mas: 100.0
        pm_ra_cosdec_mas_per_yr: 0.0
        pm_dec_mas_per_yr: 0.0
        reference_epoch_jyear: 2016.0
        reference_epoch_scale: tcb
        source: example snapshot
""",
        encoding="utf-8",
    )
    assert main(["validate", "targets", str(registry)]) == 2
    capsys.readouterr()
    assert main(["validate", "targets", str(registry), "--allow-missing-rv"]) == 0
    assert "missing_radial_velocity" in capsys.readouterr().out
