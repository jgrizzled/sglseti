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
    "IersFetchResult",
    "KernelInfo",
    "fetch_iers",
    "fetch_kernel",
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
                f"--expected-sha256 conflicts with the pinned checksum for {kernel!r} ({pinned})"
            )
    else:
        assert url is not None
        source_url = url
        pinned = expected_sha256

    return _download_atomic(source_url, output_dir, pinned=pinned)


def _download_atomic(source_url: str, output_dir: str | Path, *, pinned: str | None) -> FetchResult:
    """Atomic checksum-verified download shared by all resource fetchers."""
    filename = Path(urllib.parse.urlparse(source_url).path).name
    if not filename:
        raise EphemerisError(f"cannot derive a filename from URL {source_url!r}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename
    partial = output_dir / (filename + ".part")

    digest = hashlib.sha256()
    try:
        with (
            urllib.request.urlopen(  # noqa: S310 — explicit user-invoked fetch
                source_url, timeout=_DOWNLOAD_TIMEOUT_S
            ) as response,
            partial.open("wb") as sink,
        ):
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


@dataclass(frozen=True)
class IersFetchResult:
    path: Path
    sha256: str
    source_url: str
    coverage_start_utc: str
    coverage_end_utc: str


def fetch_iers(output_dir: str | Path, *, url: str | None = None) -> IersFetchResult:
    """Download the IERS-A Earth-orientation table to a pinned local file.

    The table becomes an explicit, checksum-identified resource that a
    request's ``iers`` block installs for its calculations — never a hidden
    astropy cache entry. No checksum can be pinned in advance (the table is
    republished weekly), so the computed SHA-256 is always reported; pin it
    in the request spec to freeze the run. The parsed coverage bounds are
    returned so staleness is visible at fetch time.
    """
    from astropy.utils import iers

    result = _download_atomic(url or iers.IERS_A_URL, output_dir, pinned=None)
    try:
        table = iers.IERS_A.open(str(result.path))
        from astropy.time import Time

        mjd = table["MJD"]
        low, high = mjd.min(), mjd.max()
        start = Time(float(getattr(low, "value", low)), format="mjd", scale="utc")
        end = Time(float(getattr(high, "value", high)), format="mjd", scale="utc")
    except Exception as exc:
        result.path.unlink(missing_ok=True)
        raise EphemerisError(
            f"downloaded IERS-A table is unreadable ({exc}); file discarded"
        ) from exc
    return IersFetchResult(
        path=result.path,
        sha256=result.sha256,
        source_url=result.source_url,
        coverage_start_utc=str(start.iso),
        coverage_end_utc=str(end.iso),
    )
