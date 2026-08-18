"""Explicit acquisition of network-backed resources.

This is the ONLY module in sglseti that performs network access, and only
when the user explicitly invokes it (``sglseti fetch`` or these functions
directly). Calculations never import this module and never download
anything: they consume pinned local files identified by content checksum
(ADR-0002).

Downloads are atomic (written to a ``.part`` file, renamed only after the
checksum verifies) so an interrupted or corrupted fetch can never be
mistaken for a valid resource.
"""

from __future__ import annotations

import hashlib
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .errors import EphemerisError

__all__ = [
    "KNOWN_KERNELS",
    "FetchResult",
    "KernelInfo",
    "fetch_kernel",
    "refresh_iers",
]

_DOWNLOAD_TIMEOUT_S = 120
_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class KernelInfo:
    """A curated, checksum-pinned JPL ephemeris kernel."""

    name: str
    url: str
    sha256: str
    coverage: str
    approx_size_mb: int
    description: str


#: Canonical kernels (ADR-0002). ``de440s`` is the sglseti canonical kernel;
#: its checksum was computed from the NAIF download on 2026-08-17.
KNOWN_KERNELS: dict[str, KernelInfo] = {
    "de440s": KernelInfo(
        name="de440s",
        url="https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp",
        sha256="sha256:c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2",
        coverage="1849-12-26 to 2150-01-22",
        approx_size_mb=32,
        description="JPL DE440s — the canonical sglseti kernel (ADR-0002)",
    ),
}


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    source_url: str


def fetch_kernel(
    kernel: str | None,
    output_dir: str | Path,
    *,
    url: str | None = None,
    expected_sha256: str | None = None,
) -> FetchResult:
    """Download an ephemeris kernel to ``output_dir`` and verify its checksum.

    Pass either a known kernel name (checksum pinned by the registry) or an
    explicit ``url`` (checksum verified only when ``expected_sha256`` is
    given, and always reported). The download is atomic; on any checksum
    mismatch nothing is left behind.
    """
    if (kernel is None) == (url is None):
        raise EphemerisError("pass exactly one of a known kernel name or --url")
    pinned: str | None
    if kernel is not None:
        try:
            info = KNOWN_KERNELS[kernel]
        except KeyError:
            known = ", ".join(sorted(KNOWN_KERNELS))
            raise EphemerisError(
                f"unknown kernel {kernel!r}; known kernels: {known} (or use --url)"
            ) from None
        source_url = info.url
        pinned = info.sha256
        if expected_sha256 is not None and expected_sha256 != pinned:
            raise EphemerisError(
                f"--expected-sha256 conflicts with the pinned checksum for "
                f"{kernel!r} ({pinned})"
            )
    else:
        assert url is not None
        source_url = url
        pinned = expected_sha256

    filename = Path(urllib.parse.urlparse(source_url).path).name
    if not filename:
        raise EphemerisError(f"cannot derive a filename from URL {source_url!r}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename
    partial = output_dir / (filename + ".part")

    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(  # noqa: S310 — explicit user-invoked fetch
            source_url, timeout=_DOWNLOAD_TIMEOUT_S
        ) as response, partial.open("wb") as sink:
            while chunk := response.read(_CHUNK_BYTES):
                digest.update(chunk)
                sink.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise EphemerisError(f"failed to download {source_url}: {exc}") from exc

    checksum = f"sha256:{digest.hexdigest()}"
    if pinned is not None and checksum != pinned:
        partial.unlink(missing_ok=True)
        raise EphemerisError(
            f"checksum mismatch for {filename}: expected {pinned}, got {checksum}; "
            "download discarded"
        )
    shutil.move(partial, destination)
    return FetchResult(path=destination, sha256=checksum, source_url=source_url)


def refresh_iers() -> str:
    """Refresh astropy's cached IERS-A Earth-orientation table.

    Improves UT1 predictions at the sub-arcsecond level; calculations work
    without it using astropy's bundled tables.
    """
    from astropy.utils import iers
    from astropy.utils.data import download_file

    try:
        path = download_file(iers.IERS_A_URL, cache="update")
    except Exception as exc:
        raise EphemerisError(f"failed to refresh IERS-A data: {exc}") from exc
    return str(path)
