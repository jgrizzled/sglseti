"""Earth-orientation (IERS) handling must never degrade silently.

Regression for review finding 3 (notes/review.md): AltAz/CIRS transforms
outside Earth-orientation coverage used to emit console warnings while the
sample stayed ``valid`` with an empty warning tuple, the fetched IERS-A
table was never actually consumed (cache refresh vs ``auto_download=False``
bundled fallback), and no IERS identity entered provenance. Now a pinned
table is installed explicitly via astropy's ``earth_orientation_table``
context, transform warnings are captured into sample/visibility warnings
with validity degradation, and the resolved IERS identity is part of the
calculation ID and manifest whenever apparent or site products exist.

The bundled ``astropy-iers-data`` IERS-A file doubles as a real fixture —
no network needed.
"""

from __future__ import annotations

import dataclasses

import pytest
from astropy.time import Time
from support import FakeEphemeris, build_small_result, make_locus_sample

from sglseti.ephemeris import (
    WARN_IERS_COVERAGE,
    IersResource,
    bundled_iers_id,
    offline_resources,
)
from sglseti.errors import EphemerisError
from sglseti.export import result_manifest
from sglseti.models import (
    CoordinateProduct,
    Epoch,
    IersSpec,
    ObservabilityConstraints,
    Observer,
    TimeList,
    Validity,
)
from sglseti.observability import visibility_sample


def _bundled_iers_a_path() -> str:
    from astropy.utils import iers

    path = getattr(iers, "IERS_A_FILE", None)
    if path is None:
        pytest.skip("astropy build does not expose a bundled IERS-A file")
    return str(path)


def _epoch_2050() -> TimeList:
    return TimeList(
        epochs=(
            Epoch(epoch_id="e2050", time=Time("2050-06-01T00:00:00", scale="utc")),
        )
    )


class TestDegradationCapture:
    def test_out_of_coverage_altaz_is_degraded_with_warnings(self) -> None:
        # The review's check: a 2050 AltAz product previously returned a
        # `valid` sample with an empty warning tuple while Python warned.
        result = build_small_result(
            coordinate_products=(CoordinateProduct.ICRS, CoordinateProduct.ALTAZ),
            time=_epoch_2050(),
        )
        assert result.samples
        for sample in result.samples:
            assert sample.altaz_alt_deg is not None
            assert sample.validity is Validity.DEGRADED
            assert any(code.startswith("astropy:") for code in sample.warnings)

    def test_in_coverage_altaz_is_clean(self) -> None:
        result = build_small_result(
            coordinate_products=(CoordinateProduct.ICRS, CoordinateProduct.ALTAZ),
        )
        for sample in result.samples:
            assert sample.validity is Validity.VALID
            assert not any(code.startswith("astropy:") for code in sample.warnings)

    def test_pinned_table_coverage_check_flags_epoch(self) -> None:
        result = build_small_result(
            coordinate_products=(CoordinateProduct.ICRS, CoordinateProduct.ALTAZ),
            time=_epoch_2050(),
            iers=IersSpec(path=_bundled_iers_a_path()),
        )
        for sample in result.samples:
            assert sample.validity is Validity.DEGRADED
            assert WARN_IERS_COVERAGE in sample.warnings

    def test_visibility_sample_carries_iers_warnings(self) -> None:
        visibility = visibility_sample(
            sample=make_locus_sample(
                observation_time_utc="2050-06-01T00:00:00.000"
            ),
            epoch=Epoch(
                epoch_id="e2050", time=Time("2050-06-01T00:00:00", scale="utc")
            ),
            observer=Observer.from_geodetic("test-site", -111.6003, 31.9583, 2096.0),
            ephemeris=FakeEphemeris((0.004, -0.002, 0.001), (0.558, -0.744, -0.323)),
            constraints=ObservabilityConstraints(
                min_target_altitude_deg=-90.0,
                max_sun_altitude_deg=90.0,
                min_moon_separation_deg=0.0,
            ),
        )
        # Degraded Earth orientation labels the sample; constraint outcomes
        # keep their normal semantics (degree-scale margins vs sub-arcsecond
        # EOP error).
        assert any(code.startswith("astropy:") for code in visibility.warnings)
        assert visibility.constraints_passed is True


class TestIersResource:
    def test_identity_coverage_and_table(self) -> None:
        resource = IersResource(IersSpec(path=_bundled_iers_a_path()))
        assert resource.iers_id.startswith("iers_a:sha256:")
        assert resource.coverage_mjd[0] < resource.coverage_mjd[1]
        assert resource.covers(Time("2020-01-01", scale="utc"))
        assert not resource.covers(Time("2050-06-01", scale="utc"))

    def test_checksum_mismatch_is_a_hard_error(self) -> None:
        with pytest.raises(EphemerisError, match="checksum mismatch"):
            IersResource(
                IersSpec(
                    path=_bundled_iers_a_path(),
                    checksum_sha256="sha256:" + "0" * 64,
                )
            )

    def test_missing_file_is_a_hard_error(self, tmp_path) -> None:
        with pytest.raises(EphemerisError, match="not found"):
            IersResource(IersSpec(path=str(tmp_path / "absent.all")))

    def test_unparseable_file_is_a_hard_error(self, tmp_path) -> None:
        bogus = tmp_path / "bogus.all"
        bogus.write_text("not an IERS table\n", encoding="utf-8")
        with pytest.raises(EphemerisError, match="failed to parse"):
            IersResource(IersSpec(path=str(bogus)))

    def test_offline_resources_installs_the_pinned_table(self) -> None:
        from astropy.utils import iers

        resource = IersResource(IersSpec(path=_bundled_iers_a_path()))
        with offline_resources(iers_table=resource.table):
            assert iers.earth_orientation_table.get() is resource.table
            assert iers.conf.auto_download is False
            assert iers.conf.iers_degraded_accuracy == "warn"
        assert iers.earth_orientation_table.get() is not resource.table


class TestProvenance:
    def test_icrs_only_requests_ignore_iers_identity(self) -> None:
        plain = build_small_result()
        pinned = build_small_result(iers=IersSpec(path=_bundled_iers_a_path()))
        assert plain.iers_id is None
        assert pinned.iers_id is None
        # Geometric ICRS never depends on Earth orientation, so the ID must
        # not churn with IERS releases.
        assert plain.calculation_id == pinned.calculation_id

    def test_apparent_products_resolve_and_pin_iers_identity(self) -> None:
        products = (CoordinateProduct.ICRS, CoordinateProduct.ALTAZ)
        bundled = build_small_result(coordinate_products=products)
        pinned = build_small_result(
            coordinate_products=products,
            iers=IersSpec(path=_bundled_iers_a_path()),
        )
        assert bundled.iers_id == bundled_iers_id()
        assert bundled.iers_id is not None and bundled.iers_id.startswith(
            "iers_bundled:astropy-iers-data=="
        )
        assert pinned.iers_id is not None
        assert pinned.iers_id.startswith("iers_a:sha256:")
        assert bundled.calculation_id != pinned.calculation_id

    def test_manifest_records_iers_identity_and_version(self) -> None:
        result = build_small_result(
            coordinate_products=(CoordinateProduct.ICRS, CoordinateProduct.ALTAZ),
        )
        manifest = result_manifest(
            result,
            generated_utc="2026-08-17T12:00:00+00:00",
            input_file_hashes={},
            output_files={},
        )
        assert manifest["science_inputs"]["iers_id"] == result.iers_id
        assert manifest["science_inputs"]["request"]["fields"]["iers"] == result.iers_id
        assert "astropy-iers-data" in manifest["run"]["versions"]

    def test_iers_identity_changes_the_science_hash(self) -> None:
        result = build_small_result(
            coordinate_products=(CoordinateProduct.ICRS, CoordinateProduct.ALTAZ),
        )
        other = dataclasses.replace(result, iers_id="iers_a:sha256:different")
        kwargs = dict(
            generated_utc="2026-08-17T12:00:00+00:00",
            input_file_hashes={},
            output_files={},
        )
        assert (
            result_manifest(result, **kwargs)["science_input_hash"]
            != result_manifest(other, **kwargs)["science_input_hash"]
        )
