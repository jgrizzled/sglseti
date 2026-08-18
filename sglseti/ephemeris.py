"""Solar-System ephemeris adapters and resource identity.

Provides the :class:`Ephemeris` protocol used by the geometry core and the
astropy-backed implementation. Resource policy is explicit and scoped:

- no implicit network access — the built-in analytic ephemeris and local JPL
  kernel files work offline, and :func:`offline_resources` scopes astropy's
  IERS auto-download off for the duration of a calculation instead of
  mutating process-global state (the prototype's ``iers.conf`` mutation is
  deliberately not ported);
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
from .models import EphemerisAdapter, EphemerisSpec
from .provenance import file_sha256

if TYPE_CHECKING:
    import numpy as np
    from astropy.time import Time

__all__ = [
    "AstropyEphemeris",
    "Ephemeris",
    "offline_resources",
]


@contextlib.contextmanager
def offline_resources() -> Iterator[None]:
    """Scoped offline policy for astropy resources.

    Inside the context, IERS auto-download is disabled; astropy falls back to
    its bundled tables (degraded-accuracy warnings are legitimate results,
    not errors). The previous configuration is restored on exit — no
    process-global mutation leaks.
    """
    from astropy.utils import iers

    with iers.conf.set_temp("auto_download", False):
        yield


@runtime_checkable
class Ephemeris(Protocol):
    """Barycentric Solar-System state provider (ICRS axes, AU)."""

    @property
    def ephemeris_id(self) -> str:
        """Path-independent resource identity for provenance."""
        ...

    def sun_barycentric_au(self, time: Time) -> np.ndarray: ...

    def earth_barycentric_au(self, time: Time) -> np.ndarray: ...


class AstropyEphemeris:
    """Astropy-backed ephemeris: built-in analytic mode or a local JPL kernel.

    The built-in mode (ERFA analytic series) is for exploration; reproducible
    scientific products should pin a local JPL kernel, whose SHA-256 becomes
    part of the ephemeris identity.
    """

    def __init__(self, spec: EphemerisSpec | None = None) -> None:
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
                    "the jpl_file ephemeris adapter requires the optional "
                    "'jplephem' dependency"
                ) from exc
            checksum = file_sha256(path)
            if self.spec.checksum_sha256 is not None and (
                self.spec.checksum_sha256 != checksum
            ):
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

    def _body_barycentric_au(self, body: str, time: Time) -> np.ndarray:
        import numpy as np
        from astropy import units as u
        from astropy.coordinates import get_body_barycentric, solar_system_ephemeris

        try:
            with solar_system_ephemeris.set(self._value):
                position: Any = get_body_barycentric(body, time)
        except ValueError as exc:
            # jplephem signals out-of-range epochs with ValueError.
            raise EphemerisCoverageError(
                f"epoch {time.isot} is outside the coverage of ephemeris "
                f"{self._id}: {exc}"
            ) from exc
        result: np.ndarray = np.asarray(position.xyz.to_value(u.au), dtype=float)
        return result
