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
