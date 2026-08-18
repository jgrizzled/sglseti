# Benchmarks

## NFR-004 representative batch

PRD requirement: 50 targets × 2 roles × 100 epochs × 25 relay samples
(250,000 locus samples) "should complete without distributed
infrastructure" on a typical laptop, and a one-target, one-night
calculation "should feel interactive".

Measured 2026-08-17 (sglseti 1.0.0rc1, single process, no parallelism):

| Machine | Apple M1 Max, 64 GB RAM, macOS 15 |
|---|---|
| Python / astropy / numpy | 3.12.2 / 8.0.1 / 2.5.2 |
| Ephemeris / observer / products | astropy builtin / Earth center / geometric ICRS only |
| Generate 250,000 samples | **938 s (~15.6 min), 266 samples/s** |
| Export (ECSV + JSON + CSV + DS9 + manifest) | 24.8 s |
| Peak RSS | 3.7 GB |
| Row status | 249,975 valid; 25 degraded (`long_propagation_span`: the farthest synthetic target's tx epochs, 2d/c ≈ 65 yr, cross the ±75 yr linear-motion bound at the latest epochs — the flag working as intended) |

Script: reproduced by the archived benchmark driver (synthetic 50-target
registry, epochs 2012–2026 at 51.3-day spacing, 550–2500 AU, count-25
sampling); no fixture values depend on it.

## Interactive scale

The shipped historical example (1 target × 2 roles × 4 epochs × 25
samples = 200 rows, ECSV+JSON) completes in ~2 s including interpreter
startup. The full shipped commensal night (73 grid epochs, apparent
coordinates, rates, visibility, planning) takes ~60 s.

## Notes

- Cost is dominated by per-sample astropy calls (catalog propagation,
  ephemeris, observer projection); requesting apparent coordinates
  multiplies transforms and `rates` triples geometry evaluations.
- Generation is embarrassingly parallel over target/role/epoch and IDs are
  input-derived, so future parallelism or caching cannot change output
  identity; none ships in v1 because the requirement is met without it.
- Memory scales with the retained result (~15 KB/sample at peak here);
  chunked writing for larger-than-memory batches is a post-v1 concern.
  (Addressed in v1.1 — see below.)

## v1.1 archive-scale execution (roadmap §3.4)

Measured 2026-08-18 on the same machine and library versions as above,
with `benchmarks/archive_scale.py` (same NFR-004 configuration: astropy
builtin ephemeris, Earth center, geometric ICRS only). Note on comparing
against the rc1 table: `RESULT_SCHEMA_VERSION` 2 (rc2) added the
segment-boundary coordinates, tripling the geometry evaluations per
sample — re-measured at head-before-item-6.5, the reference small batch
(4 targets x 2 roles x 25 epochs x 25 samples = 5,000 samples) ran at
**90 samples/s**. With the v1.1 identity-keyed caches (providers by
content hash, target states per TDB epoch, scalar ephemeris positions,
site GCRS offsets — all pure and bit-identical, verified by the test
suite):

| Scenario | Result |
|---|---|
| Small batch, 5,000 samples | 13.0 s, **383 samples/s** (was 55.5 s / 90 samples/s: ~4.3x) |
| Small batch, tabular spacecraft observer | 15.0 s, **333 samples/s** — Hermite table interpolation is not a bottleneck (measured 2026-08-18, item 6.11) |
| NFR-004 batch, 250,000 samples | 675 s (~11.2 min), **370 samples/s** — rc1's 938 s produced one third of the geometry per row (schema v1) |
| Vectorized `states_at` x500 epochs | 8 ms vs 700 ms scalar (~90x) |
| Batch export, 250,000 rows (ECSV+CSV) | 58 s, python-heap peak **2.18 GB** |
| Streaming export, 250,000 rows (CSV + 25k-row ECSV parts) | 57 s, python-heap peak **227 MB** (~10x lower) |
| Monte Carlo locus uncertainty, 256 samples | ~1.0 s |
| Full test suite | 18 s (was ~50 s before the caches) |

Remaining hot spot: the rx role's per-distance catalog propagation
(catalog epoch `t - 2z/c` differs for every relay distance, so the
per-epoch state memo cannot collapse it; antipode/tx epochs are
z-independent and fully cached). Vectorizing that inside the geometry
model is the next lever if archive workloads need it.

Deterministic chunking (`plan_calculation` + `iter_locus_chunks`) and the
bounded-memory `write_samples_stream` writer make larger-than-memory
batches practical: chunks arrive in the documented product order with
unchanged identities, any index range is independently reproducible, and
the streamed `samples.csv` is byte-identical to the batch writer's file.
