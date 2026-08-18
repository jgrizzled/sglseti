# From the prototype

sglseti began as a port of selected code from the `sgl-search-planner`
prototype (~2,000 lines). This note records what was carried over, what was
materially changed, and what was deliberately left behind — so no prototype
behavior is mistaken for reviewed science. The prototype directory itself
was removed from the repository at the 1.0.0rc1 release candidate (it
remains in git history before that point).

## Ported (with changes)

| Prototype | sglseti | Material changes |
|---|---|---|
| `config.py` strict YAML loading, immutable records | `config.py`, `targets.py`, `models.py` | split the monolithic `Campaign`; duplicate-key-rejecting loader; finite-value/frame/epoch-scale/provenance requirements; explicit missing-RV policy; unknown keys rejected |
| `geometry.py` target propagation, relay vector, rates | `geometry.py` | role epochs made public `DirectionSolution` fields with SSB-arrival semantics and physical-event diagnostics; model named/versioned `tusay2022_eq5_7_v1`; catalog reference scale honored (prototype forced TDB); validity/warnings instead of bare exceptions; no process-global IERS mutation; apparent products rebuilt on true barycentric cartesian coordinates (the prototype's finite-distance CIRS construction was flagged and replaced) |
| `partition.py` reciprocal-distance cells | `sampling.py` | `SearchCell` → `RangeSegment`; coverage/include/exclude semantics removed; ordering flipped to near→far with exact endpoint bounds; representative distance made explicit |
| `planner.py` `_time_grid`, `_find_best_time`, `_zone_for_cells`, `_group_cells`, `_stable_hash` | `generate.py`, `observability.py`, `planning.py`, `provenance.py` | ledger filtering and profile/visit/completion fields removed; single "best time" replaced by *all* contiguous windows with documented representatives; radius components kept separate; `default=str` hashing replaced by a versioned canonical serializer with typed time/quantity/enum handling and path rejection |
| `output.py` CSV/DS9 patterns | `export.py` | deterministic columns kept; observation-results template **not** ported; ECSV and versioned JSON added; DS9 widths must be explicitly assumed |
| `cli.py` argparse/error boundary | `cli.py` | `cells`/`coverage`/`ingest`/`report` replaced by `validate`/`samples`/`generate`/`plan`/`fetch`; exit policy documented |

## Not ported

- `ledger.py` and every observation/coverage/completion concept — the
  package boundary excludes them (CI-enforced).
- The campaign `Profile` (band, signal class, visit cadence, quality).
- The SIMBAD helper (optional post-v1 extra; its hard-coded J2000 epoch was
  one of the reasons it did not ship).
- The prototype geometry smoke test: no prototype numerical output was ever
  frozen as expected truth. All regression values derive from the two
  independent Phase 0 oracles (`tests/data/reference/README.md`).

## Scientific corrections relative to the prototype

The prototype's role-epoch offsets were verified correct, but only under
the arrival-indexed catalog convention it never stated. sglseti makes that
convention explicit everywhere (see
[science/geometry_models.md](science/geometry_models.md)), returns the
physical event epochs the prototype hid, and ships a negative regression
fixture that fails any reintroduction of the double-retarded Rx epoch.
