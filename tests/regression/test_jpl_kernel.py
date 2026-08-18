"""Real-kernel regression for the jpl_file ephemeris adapter.

Uses the committed DE440s excerpt (tests/data/kernels/README.md) so the
file-backed code path — checksum identity, kernel reads, coverage errors —
runs offline in default CI against the canonical ephemeris solution.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.time import Time
from support import REFERENCE_DIR, load_reference_fixture, separation_arcsec

from sglseti.ephemeris import AstropyEphemeris
from sglseti.errors import EphemerisCoverageError, EphemerisError
from sglseti.geometry import Tusay2022Eq57V1, compute_relay_solution
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    EphemerisAdapter,
    EphemerisSpec,
    Observer,
    Role,
    Target,
)
from sglseti.provenance import file_sha256

KERNEL_PATH = REFERENCE_DIR.parent / "kernels" / "de440s_excerpt_2010-2035.bsp"

# Pinned in tests/data/kernels/README.md; a change means the committed
# fixture was modified and needs a documented reason.
KERNEL_SHA256 = "sha256:eca51b9422e7d3d0266b271757f575671dca585cf4cd744a87cbf4870d5f7530"

T_2021 = Time("2021-11-06T00:00:00", scale="utc")


@pytest.fixture(scope="module")
def kernel_ephemeris() -> AstropyEphemeris:
    return AstropyEphemeris(
        EphemerisSpec(
            adapter=EphemerisAdapter.JPL_FILE,
            path=str(KERNEL_PATH),
            checksum_sha256=KERNEL_SHA256,
        )
    )


def test_committed_fixture_is_unmodified() -> None:
    assert file_sha256(KERNEL_PATH) == KERNEL_SHA256


def test_ephemeris_identity_is_content_checksum(
    kernel_ephemeris: AstropyEphemeris,
) -> None:
    assert kernel_ephemeris.ephemeris_id == f"jpl_file:{KERNEL_SHA256}"


def test_checksum_mismatch_rejected() -> None:
    with pytest.raises(EphemerisError, match="checksum mismatch"):
        AstropyEphemeris(
            EphemerisSpec(
                adapter=EphemerisAdapter.JPL_FILE,
                path=str(KERNEL_PATH),
                checksum_sha256="sha256:" + "0" * 64,
            )
        )


def test_kernel_agrees_with_builtin_at_builtin_accuracy(
    kernel_ephemeris: AstropyEphemeris,
) -> None:
    builtin = AstropyEphemeris()
    for body in ("sun_barycentric_au", "earth_barycentric_au"):
        from_kernel = getattr(kernel_ephemeris, body)(T_2021)
        from_builtin = getattr(builtin, body)(T_2021)
        difference = float(np.linalg.norm(from_kernel - from_builtin))
        # The builtin analytic series is good to ~100-200 km against DE440s;
        # a nonzero difference also proves the kernel was actually read.
        assert 1e-9 < difference < 5e-6


@pytest.mark.filterwarnings("ignore:ERFA function.*dubious year")
def test_out_of_coverage_epoch_raises(kernel_ephemeris: AstropyEphemeris) -> None:
    with pytest.raises(EphemerisCoverageError, match="outside the coverage"):
        kernel_ephemeris.sun_barycentric_au(Time("2050-01-01T00:00:00", scale="utc"))


def test_alpha_cen_locus_with_pinned_kernel(
    kernel_ephemeris: AstropyEphemeris,
) -> None:
    """The published-epoch anchor reproduces with the canonical kernel too."""
    fixture = load_reference_fixture("alpha_cen_2021-11-06.yaml")
    astrometry = fixture["inputs"]["astrometry"]
    target = Target(
        target_id="alpha-cen-a",
        display_name="Alpha Centauri A",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=astrometry["ra_deg"],
            dec_deg=astrometry["dec_deg"],
            parallax_mas=astrometry["parallax_mas"],
            pm_ra_cosdec_mas_per_yr=astrometry["pm_ra_cosdec_mas_per_yr"],
            pm_dec_mas_per_yr=astrometry["pm_dec_mas_per_yr"],
            radial_velocity_km_s=astrometry["radial_velocity_km_s"],
            reference_epoch_jyear=astrometry["reference_epoch_jyear"],
            reference_epoch_scale=astrometry["reference_epoch_scale"],
            source="SIMBAD display captured 2026-08-17 (fixture)",
        ),
    )
    observer_data = fixture["inputs"]["observer"]
    observer = Observer.from_geodetic(
        "gbt",
        observer_data["longitude_deg"],
        observer_data["latitude_deg"],
        observer_data["height_m"],
    )
    solution = compute_relay_solution(
        target=target,
        observation_time=Time(fixture["inputs"]["t_o_utc"], scale="utc"),
        z_au=550.0,
        role=Role.ANTIPODE,
        observer=observer,
        ephemeris=kernel_ephemeris,
        model=Tusay2022Eq57V1(),
    )
    expected = fixture["expected"]["antipode_z550"]
    separation = separation_arcsec(
        solution.los_icrs_ra_deg,
        solution.los_icrs_dec_deg,
        expected["los_ra_deg"],
        expected["los_dec_deg"],
    )
    # Within the fixture's reproduction tolerance, and specifically within
    # the builtin-vs-DE440s ephemeris difference envelope (~0.3 mas at
    # 550 au from ~10^2 km of Solar-position difference).
    assert separation < fixture["tolerance"]["reproducibility_arcsec"]
    assert separation < 0.005
    assert solution.ephemeris_id == f"jpl_file:{KERNEL_SHA256}"
