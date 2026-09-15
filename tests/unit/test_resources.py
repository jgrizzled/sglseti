"""Offline tests for the explicit resource-acquisition layer.

Download mechanics are exercised through file:// URLs so default tests never
touch the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sglseti.errors import EphemerisError
from sglseti.provenance import file_sha256
from sglseti.resources import KNOWN_KERNELS, fetch_kernel


def make_source(tmp_path: Path) -> tuple[str, str]:
    source = tmp_path / "source" / "kernel.bsp"
    source.parent.mkdir()
    source.write_bytes(b"not a real kernel, but bytes with a checksum")
    return source.as_uri(), file_sha256(source)


def test_registry_pins_the_canonical_kernel() -> None:
    info = KNOWN_KERNELS["de440s"]
    assert info.url.startswith("https://naif.jpl.nasa.gov/")
    assert info.sha256 == (
        "sha256:c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2"
    )
    assert "1849" in info.coverage and "2150" in info.coverage


def test_fetch_by_url_reports_and_verifies_checksum(tmp_path: Path) -> None:
    url, checksum = make_source(tmp_path)
    result = fetch_kernel(None, tmp_path / "out", url=url, expected_sha256=checksum)
    assert result.path == tmp_path / "out" / "kernel.bsp"
    assert result.path.is_file()
    assert result.sha256 == checksum
    assert file_sha256(result.path) == checksum


def test_fetch_without_expectation_still_reports_checksum(tmp_path: Path) -> None:
    url, checksum = make_source(tmp_path)
    result = fetch_kernel(None, tmp_path / "out", url=url)
    assert result.sha256 == checksum


def test_checksum_mismatch_leaves_nothing_behind(tmp_path: Path) -> None:
    url, _ = make_source(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(EphemerisError, match="checksum mismatch.*discarded"):
        fetch_kernel(None, out, url=url, expected_sha256="sha256:" + "0" * 64)
    assert not any(out.iterdir())


def test_unknown_kernel_name(tmp_path: Path) -> None:
    with pytest.raises(EphemerisError, match="unknown kernel 'de999'.*de440s"):
        fetch_kernel("de999", tmp_path)


def test_name_and_url_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(EphemerisError, match="exactly one"):
        fetch_kernel("de440s", tmp_path, url="file:///x.bsp")
    with pytest.raises(EphemerisError, match="exactly one"):
        fetch_kernel(None, tmp_path)


def test_expected_sha_conflicting_with_pin_rejected(tmp_path: Path) -> None:
    with pytest.raises(EphemerisError, match="conflicts with the pinned checksum"):
        fetch_kernel("de440s", tmp_path, expected_sha256="sha256:" + "0" * 64)


def test_cli_fetch_ephemeris_by_url(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from sglseti.cli import main

    url, checksum = make_source(tmp_path)
    out = tmp_path / "resources"
    code = main(
        [
            "fetch",
            "ephemeris",
            "--url",
            url,
            "--expected-sha256",
            checksum,
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert f"sha256:  {checksum}" in output
    assert "adapter: jpl_file" in output
    assert str(out / "kernel.bsp") in output


def test_cli_fetch_ephemeris_bad_checksum_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sglseti.cli import main

    url, _ = make_source(tmp_path)
    code = main(
        [
            "fetch",
            "ephemeris",
            "--url",
            url,
            "--expected-sha256",
            "sha256:" + "0" * 64,
            "--output-dir",
            str(tmp_path / "resources"),
        ]
    )
    assert code == 2
    assert "checksum mismatch" in capsys.readouterr().err
