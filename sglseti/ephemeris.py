"""Solar-System ephemeris adapters and resource identity.

Provides the :class:`Ephemeris` protocol used by the geometry core and the
astropy-backed implementation. Resource policy is explicit and scoped:

- no implicit network access — the built-in analytic ephemeris and local JPL
  kernel files work offline, and :func:`offline_resources` scopes astropy's
  IERS auto-download off for the duration of a calculation instead of
  mutating process-global state (the prototype's ``iers.conf`` mutation is
  deliberately not ported); a pinned :class:`IersResource` table is
  installed the same scoped way, and degraded Earth-orientation accuracy is
  forced to warn so callers can capture it into product validity;
- file-backed resources are identified by content checksum, never by path;
- epochs outside a kernel's coverage raise
  :class:`~sglseti.errors.EphemerisCoverageError` — an invalid status, never
  an apparently valid row.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .errors import EphemerisCoverageError, EphemerisError
from .models import EphemerisAdapter, EphemerisSpec, IersSpec
from .provenance import file_sha256

if TYPE_CHECKING:
    import numpy as np
    from astropy.time import Time

__all__ = [
    "WARN_IERS_COVERAGE",
    "AstropyEphemeris",
    "Ephemeris",
    "IersResource",
    "bundled_iers_id",
    "offline_resources",
]

#: Warning code attached to apparent/site products computed at an epoch
#: outside a pinned IERS table's tabulated range.
WARN_IERS_COVERAGE = "iers_out_of_coverage"


@contextlib.contextmanager
def offline_resources(iers_table: Any | None = None) -> Iterator[None]:
    """Scoped offline policy for astropy resources.

    Inside the context, IERS auto-download is disabled and degraded
    Earth-orientation accuracy is forced to warn (never raise, never pass
    silently) so callers can capture the warnings into product validity.
    The table-age limit (``auto_max_age``) is lifted as well: with downloads
    off, astropy would otherwise raise outright for any epoch past the
    bundled table's predictive range once that table is more than 30 days
    old — turning every offline install into a time bomb. Coverage
    degradation still surfaces through the transform warnings captured
    above.
    When ``iers_table`` is given (an :class:`IersResource` table), it is
    installed explicitly via astropy's ``earth_orientation_table`` context —
    the pinned file is *used*, not merely cached; otherwise astropy's
    bundled tables apply. The previous configuration is restored on exit —
    no process-global mutation leaks.
    """
    from astropy.utils import iers

    with contextlib.ExitStack() as stack:
        stack.enter_context(iers.conf.set_temp("auto_download", False))
        stack.enter_context(iers.conf.set_temp("auto_max_age", None))
        stack.enter_context(iers.conf.set_temp("iers_degraded_accuracy", "warn"))
        if iers_table is not None:
            stack.enter_context(iers.earth_orientation_table.set(iers_table))
        yield


def bundled_iers_id() -> str:
    """Identity of astropy's bundled Earth-orientation tables."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        bundled_version = version("astropy-iers-data")
    except PackageNotFoundError:  # pragma: no cover
        bundled_version = "unknown"
    return f"iers_bundled:astropy-iers-data=={bundled_version}"


class IersResource:
    """A pinned IERS-A table: content identity, coverage, loaded table.

    Mirrors the file-backed ephemeris policy: the file is identified by
    SHA-256 (an optional spec checksum makes a mismatch a hard error), its
    coverage bounds are parsed up front, and the loaded table is installed
    per calculation through :func:`offline_resources`.
    """

    def __init__(self, spec: IersSpec) -> None:
        self.spec = spec
        path = Path(spec.path)
        if not path.is_file():
            raise EphemerisError(f"IERS table not found: {path}")
        checksum = file_sha256(path)
        if spec.checksum_sha256 is not None and spec.checksum_sha256 != checksum:
            raise EphemerisError(
                f"IERS table checksum mismatch for {path.name}: "
                f"expected {spec.checksum_sha256}, got {checksum}"
            )
        from astropy.utils import iers

        try:
            self.table = iers.IERS_A.open(str(path))
            mjd = self.table["MJD"]
            low, high = mjd.min(), mjd.max()
            self.coverage_mjd = (
                float(getattr(low, "value", low)),
                float(getattr(high, "value", high)),
            )
        except EphemerisError:
            raise
        except Exception as exc:
            raise EphemerisError(f"failed to parse IERS-A table {path.name}: {exc}") from exc
        self._id = f"iers_a:{checksum}"

    @property
    def iers_id(self) -> str:
        return self._id

    def covers(self, time: Time) -> bool:
        """Whether ``time`` lies inside the table's tabulated MJD range."""
        mjd = float(time.utc.mjd)
        return self.coverage_mjd[0] <= mjd <= self.coverage_mjd[1]


@runtime_checkable
class Ephemeris(Protocol):
    """Barycentric Solar-System state provider (ICRS axes, AU)."""

    @property
    def ephemeris_id(self) -> str:
        """Path-independent resource identity for provenance."""
        ...

    def sun_barycentric_au(self, time: Time) -> np.ndarray: ...

    def earth_barycentric_au(self, time: Time) -> np.ndarray: ...

    def moon_barycentric_au(self, time: Time) -> np.ndarray: ...

    def body_barycentric_au(self, body: str, time: Time) -> np.ndarray:
        """Barycentric position of a named Solar-System body (§2.4).

        Backs the ``solar_system_body`` observer family. A body the
        resource cannot serve raises
        :class:`~sglseti.errors.EphemerisError`, never a fabricated
        position.
        """
        ...


class AstropyEphemeris:
    """Astropy-backed ephemeris: built-in analytic mode or a local JPL kernel.

    The built-in mode (ERFA analytic series) is for exploration; reproducible
    scientific products should pin a local JPL kernel, whose SHA-256 becomes
    part of the ephemeris identity.
    """

    def __init__(self, spec: EphemerisSpec | None = None) -> None:
        from collections import OrderedDict

        self._position_cache: OrderedDict[tuple[str, float, float], Any] = OrderedDict()
        self.spec = spec if spec is not None else EphemerisSpec()
        if self.spec.adapter is EphemerisAdapter.ASTROPY_BUILTIN:
            self._value = "builtin"
            self._id = "astropy_builtin"
        else:
            assert self.spec.path is not None
            path = Path(self.spec.path)
            if not path.is_file():
                raise EphemerisError(f"ephemeris kernel not found: {path}")
            try:
                import jplephem  # noqa: F401
            except ImportError as exc:
                raise EphemerisError(
                    "the jpl_file ephemeris adapter requires the optional 'jplephem' dependency"
                ) from exc
            checksum = file_sha256(path)
            if self.spec.checksum_sha256 is not None and (self.spec.checksum_sha256 != checksum):
                raise EphemerisError(
                    f"ephemeris kernel checksum mismatch for {path.name}: "
                    f"expected {self.spec.checksum_sha256}, got {checksum}"
                )
            self._value = str(path)
            self._id = f"jpl_file:{checksum}"

    @property
    def ephemeris_id(self) -> str:
        return self._id

    def sun_barycentric_au(self, time: Time) -> np.ndarray:
        return self._body_barycentric_au("sun", time)

    def earth_barycentric_au(self, time: Time) -> np.ndarray:
        return self._body_barycentric_au("earth", time)

    def moon_barycentric_au(self, time: Time) -> np.ndarray:
        # Needed only by observability (Moon-separation constraints); a
        # kernel without a Moon segment fails here with a KeyError from
        # jplephem, surfaced as an EphemerisError below.
        return self._body_barycentric_au("moon", time)

    def body_barycentric_au(self, body: str, time: Time) -> np.ndarray:
        """Barycentric position of any body the resource can serve."""
        return self._body_barycentric_au(body, time)

    def _body_barycentric_au(self, body: str, time: Time) -> np.ndarray:

        # Scalar epochs are memoized per (body, two-double TDB JD) — a pure,
        # bit-identical reuse of repeated target/role/epoch evaluations
        # (§3.4). Vector times pass straight through.
        key = None
        if time.isscalar:
            tdb = time.tdb
            key = (body, float(tdb.jd1), float(tdb.jd2))
            cached = self._position_cache.get(key)
            if cached is not None:
                self._position_cache.move_to_end(key)
                copy: np.ndarray = cached.copy()
                return copy
        position_au = self._compute_body_barycentric_au(body, time)
        if key is not None:
            self._position_cache[key] = position_au.copy()
            if len(self._position_cache) > self._POSITION_CACHE_MAX:
                self._position_cache.popitem(last=False)
        result: np.ndarray = position_au
        return result

    #: Bound on the per-instance scalar-position memo (three bodies x epochs).
    _POSITION_CACHE_MAX = 16384

    def _compute_body_barycentric_au(self, body: str, time: Time) -> np.ndarray:
        import numpy as np
        from astropy import units as u
        from astropy.coordinates import get_body_barycentric, solar_system_ephemeris

        try:
            with solar_system_ephemeris.set(self._value):
                position: Any = get_body_barycentric(body, time)
        except ValueError as exc:
            # jplephem signals out-of-range epochs with ValueError.
            raise EphemerisCoverageError(
                f"epoch {time.isot} is outside the coverage of ephemeris {self._id}: {exc}"
            ) from exc
        except KeyError as exc:
            raise EphemerisError(
                f"ephemeris {self._id} has no segment for body {body!r}; "
                "use a kernel that includes it (or the builtin adapter)"
            ) from exc
        result: np.ndarray = np.asarray(position.xyz.to_value(u.au), dtype=float)
        return result
