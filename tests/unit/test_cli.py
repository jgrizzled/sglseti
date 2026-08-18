from __future__ import annotations

import importlib.metadata

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
