"""Archive-scale benchmark driver (roadmap §3.4).

Measures the execution features added for archive surveys — identity-keyed
provider/state caching, vectorized state evaluation, deterministic chunked
iteration, and bounded-memory streaming export — plus Monte Carlo
uncertainty propagation, on a deterministic synthetic registry with the
astropy built-in ephemeris (the same configuration as the NFR-004 entry in
``docs/benchmarks.md``).

Run from the repository root:

    uv run python benchmarks/archive_scale.py            # laptop scale
    uv run python benchmarks/archive_scale.py --full     # NFR-004 scale

No fixture or test values depend on this script's output.
"""

from __future__ import annotations

import argparse
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np
from astropy.time import Time

from sglseti.export import write_products, write_samples_stream
from sglseti.generate import generate_loci
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.models import (
    AstrometricState,
    EndpointKind,
    GeometryRequest,
    Observer,
    OutputFormat,
    ParameterProvenance,
    RelayRange,
    Role,
    SamplingKind,
    SamplingSpec,
    Target,
    TimeGrid,
)
from sglseti.providers import (
    clear_provider_cache,
    provider_cache_stats,
    resolve_target_state_provider,
)
from sglseti.targets import TargetRegistry
from sglseti.uncertainty import propagate_locus_uncertainty


def synthetic_target(index: int, *, with_uncertainty: bool = False) -> Target:
    provenance = ()
    if with_uncertainty:
        provenance = (
            ParameterProvenance("ra_deg", "benchmark", 1.0, "mas"),
            ParameterProvenance("dec_deg", "benchmark", 1.0, "mas"),
            ParameterProvenance("parallax_mas", "benchmark", 0.3, "mas"),
        )
    return Target(
        target_id=f"synth-{index:03d}",
        display_name=f"Synthetic {index}",
        endpoint_kind=EndpointKind.STAR,
        astrometry=AstrometricState(
            ra_deg=(index * 47.3) % 360.0,
            dec_deg=-80.0 + (index * 137.5) % 160.0,
            pm_ra_cosdec_mas_per_yr=-900.0 + index * 37.0,
            pm_dec_mas_per_yr=400.0 - index * 21.0,
            reference_epoch_jyear=2016.0,
            reference_epoch_scale="tdb",
            source="synthetic benchmark values",
            parallax_mas=60.0 + (index * 13.7) % 640.0,
            radial_velocity_km_s=-40.0 + index * 3.0,
        ),
        parameter_provenance=provenance,
    )


def make_request(target_count: int, epoch_count: int) -> GeometryRequest:
    cadence_s = (14.0 * 365.25 * 86_400.0) / (epoch_count - 1)
    return GeometryRequest(
        target_ids=tuple(f"synth-{i:03d}" for i in range(target_count)),
        roles=(Role.RX, Role.TX),
        time=TimeGrid(
            start=Time("2012-01-01T00:00:00", scale="utc"),
            stop=Time("2026-01-01T00:00:00", scale="utc"),
            cadence_s=cadence_s,
        ),
        observer=Observer.earth_center(),
        relay_range=RelayRange(550.0, 2500.0),
        sampling=SamplingSpec(kind=SamplingKind.COUNT, count=25),
        model_id="tusay2022_eq5_7_v1",
        output_formats=(OutputFormat.ECSV, OutputFormat.CSV),
    )


def bench_generate(target_count: int, epoch_count: int) -> None:
    registry = TargetRegistry.from_targets(
        tuple(synthetic_target(i) for i in range(target_count))
    )
    request = make_request(target_count, epoch_count)
    clear_provider_cache()
    started = time.perf_counter()
    result = generate_loci(request, registry)
    elapsed = time.perf_counter() - started
    stats = provider_cache_stats()
    print(
        f"generate {len(result.samples):>8} samples: {elapsed:8.1f} s "
        f"({len(result.samples) / elapsed:7.0f} samples/s)  "
        f"provider-resolve hits/misses: {stats['hits']}/{stats['misses']}"
    )

    # Export comparison feeds both writers the SAME held corridors, so the
    # numbers isolate the writers. The memory point of streaming is the
    # end-to-end chunked pipeline (iter_locus_chunks -> write_samples_stream)
    # never holding the full sample table at all — a design property, not a
    # per-call measurement.
    with tempfile.TemporaryDirectory() as tmp:
        tracemalloc.start()
        started = time.perf_counter()
        write_products(result, Path(tmp) / "batch", generated_utc="benchmark")
        batch_time = time.perf_counter() - started
        _, batch_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        started = time.perf_counter()
        write_samples_stream(
            iter(result.corridors),
            Path(tmp) / "stream",
            calculation_id=result.calculation_id,
            model_id=request.model_id,
            result_warnings=result.warnings,
            rows_per_ecsv_part=25_000,
        )
        stream_time = time.perf_counter() - started
        _, stream_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    print(
        f"export batch:  {batch_time:8.1f} s, python-heap peak {batch_peak / 1e6:8.1f} MB"
    )
    print(
        f"export stream: {stream_time:8.1f} s, python-heap peak {stream_peak / 1e6:8.1f} MB "
        "(25k-row ECSV parts)"
    )


def bench_spacecraft(target_count: int, epoch_count: int) -> None:
    """The same batch with a tabular spacecraft observer (§3.4 item 11)."""
    import numpy as np
    from astropy.table import Table as AstropyTable
    from astropy.time import Time, TimeDelta

    from sglseti.ephemeris import AstropyEphemeris
    from sglseti.provenance import file_sha256

    registry = TargetRegistry.from_targets(
        tuple(synthetic_target(i) for i in range(target_count))
    )
    ephemeris = AstropyEphemeris()
    start = Time("2011-12-01T00:00:00", scale="utc").tdb
    half = TimeDelta(0.5, format="jd", scale="tdb")
    epochs_jd, positions, velocities = [], [], []
    for node in range(0, 5300, 5):  # 5-day nodes through 2026-06
        t = start + TimeDelta(float(node), format="jd", scale="tdb")
        earth = ephemeris.earth_barycentric_au(t)
        velocity = (
            ephemeris.earth_barycentric_au(t + half)
            - ephemeris.earth_barycentric_au(t - half)
        )
        epochs_jd.append(float(t.tdb.jd))
        positions.append(earth + np.array([0.01, 0.0, 0.0]))  # L2-scale offset
        velocities.append(velocity)
    with tempfile.TemporaryDirectory() as tmp:
        table_path = Path(tmp) / "craft.ecsv"
        AstropyTable(
            {
                "epoch_tdb_jd": epochs_jd,
                "x_au": [p[0] for p in positions],
                "y_au": [p[1] for p in positions],
                "z_au": [p[2] for p in positions],
                "vx_au_per_day": [v[0] for v in velocities],
                "vy_au_per_day": [v[1] for v in velocities],
                "vz_au_per_day": [v[2] for v in velocities],
            }
        ).write(table_path, format="ascii.ecsv", overwrite=True)
        request_values = make_request(target_count, epoch_count)
        request = GeometryRequest(
            **{
                **{
                    f.name: getattr(request_values, f.name)
                    for f in request_values.__dataclass_fields__.values()
                },
                "observer": Observer.spacecraft_table(
                    "bench-craft",
                    str(table_path),
                    checksum_sha256=file_sha256(table_path),
                ),
            }
        )
        clear_provider_cache()
        started = time.perf_counter()
        result = generate_loci(request, registry)
        elapsed = time.perf_counter() - started
    print(
        f"generate {len(result.samples):>8} samples (spacecraft observer): "
        f"{elapsed:8.1f} s ({len(result.samples) / elapsed:7.0f} samples/s)"
    )


def bench_vectorized(epoch_count: int = 500) -> None:
    clear_provider_cache()
    provider = resolve_target_state_provider(synthetic_target(0))
    epochs = Time(
        np.linspace(2012.0, 2026.0, epoch_count), format="jyear", scale="tdb"
    )
    started = time.perf_counter()
    for index in range(epoch_count):
        provider.state_at(epochs[index])
    scalar = time.perf_counter() - started
    started = time.perf_counter()
    provider.states_at(epochs)
    vector = time.perf_counter() - started
    print(
        f"target states x{epoch_count}: scalar {scalar * 1000:7.0f} ms, "
        f"vectorized {vector * 1000:6.1f} ms ({scalar / vector:5.0f}x)"
    )


def bench_uncertainty(count: int = 256) -> None:
    from sglseti.ephemeris import AstropyEphemeris

    clear_provider_cache()
    target = synthetic_target(0, with_uncertainty=True)
    started = time.perf_counter()
    result = propagate_locus_uncertainty(
        target=target,
        role=Role.RX,
        observation_time=Time("2021-11-06T00:00:00", scale="utc"),
        observer=Observer.earth_center(),
        z_au=1000.0,
        ephemeris=AstropyEphemeris(),
        model=Tusay2022Eq57V1(),
        seed=1,
        count=count,
    )
    elapsed = time.perf_counter() - started
    print(
        f"uncertainty x{count} samples: {elapsed:6.1f} s "
        f"(confidence radius {result.confidence_radius_arcsec:.3f} arcsec)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="NFR-004 scale (50 targets x 2 roles x 100 epochs x 25 samples)",
    )
    args = parser.parse_args()
    targets, epochs = (50, 100) if args.full else (4, 25)
    print(f"scale: {targets} targets x 2 roles x {epochs} epochs x 25 samples")
    bench_generate(targets, epochs)
    bench_spacecraft(targets, epochs)
    bench_vectorized()
    bench_uncertainty()


if __name__ == "__main__":
    main()
