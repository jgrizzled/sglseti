# v1 acceptance status (PRD §15)

Status as of 2026-08-17, against `notes/sglseti_python_package_prd.md` §15.
Evidence cites tests (all green locally: `uv run pytest` — 269 tests,
`ruff`, `mypy --strict`).

## Historical target generation

- [x] All requested target/role/range combinations for arbitrary past UTC
  epochs — `tests/integration/test_generate_historical.py` (2012–2024
  epochs, full product).
- [x] Every row retains its input `epoch_id`, joinable —
  `test_every_epoch_id_joins_back_losslessly`,
  `test_products_consumable_with_stdlib_and_astropy_only`.
- [x] Same engine and model for past and future —
  `test_epoch_neutrality_past_and_future_in_one_list`; the commensal path
  uses the identical `generate_loci`.
- [x] No archive account/API/observation database/ledger —
  `test_boundary_no_ledger_coverage_or_sqlite_implementation`.

## Geometry

- [x] `antipode`/`rx`/`tx` implement reviewed `tusay2022_eq5_7_v1` —
  `tests/regression/test_geometry_fixtures.py` against the Phase 0
  independent-oracle fixtures.
- [x] Catalog-direction epoch distinguished from physical target-event
  epoch on every row — `DirectionSolution`/`LocusSample` fields;
  `test_rows_carry_full_scientific_metadata`.
- [x] Rx regression reproduces `u_rx = t_o − 2z/c` and detects an extra
  `−d/c` — `TestConstantVelocitySynthetic`, `TestDoubleRetardedNegative`
  (negative fixture verified to coincide with the real astropy failure
  mode, Phase 0 review).
- [x] High-proper-motion Rx/Tx distinction — `TestBarnardScaleCheck`.
- [x] Ordered, distance-addressable corridor — `RangeSegment` ordering
  tests; corridor `sample_ids` + per-sample `z_au`.
- [x] Explicit origin/frame/time scale/correction —
  `test_solution_metadata_is_explicit`; docs/conventions.md.
- [x] Invalid/degraded carry machine-readable status —
  `test_coverage_failure_isolated_to_its_combination`,
  `test_missing_radial_velocity_degrades_explicitly`.

## Commensal target generation

- [x] Current/future targets on a time grid — `test_grid_materialization`,
  `tests/integration/test_plan_commensal.py`.
- [x] AltAz, Sun altitude, Moon separation, angular rates —
  `tests/unit/test_observability.py`, `test_rates_and_apparent_products_populated`.
- [x] Simple constraints → candidate windows — `TestWindows` (disjoint
  windows, boundaries, never-visible).
- [x] Adjacent reciprocal-distance grouping into circular pointings —
  `tests/unit/test_planning.py`.
- [x] Pointings labeled unscheduled candidate zones — model/docs/help text;
  `test_no_schedule_language`.

## Outputs and reproducibility

- [x] ECSV/JSON/CSV/DS9 from one result model — `tests/unit/test_export.py`;
  `test_exporters_do_not_import_geometry`.
- [x] JSON provenance manifest with every product — `TestManifest`.
- [x] File-backed resources identified by checksum —
  `tests/regression/test_jpl_kernel.py`, `test_calculation_id_is_path_independent`.
- [x] Stable IDs exclude output path and timestamp —
  `test_science_hash_independent_of_run_circumstance`, provenance tests.
- [x] Documented offline rerun reproduces identical science IDs and
  equivalent output — `test_offline_rerun_reproduces_science_ids_and_rows`
  (network blocked at audit-hook level, pinned kernel, different cwd).

## Quality and documentation

- [~] Default tests pass on supported Python versions — green locally
  (3.12); the 3.11–3.13 × 3-OS CI matrix is configured
  (`.github/workflows/ci.yml`) but must run before tagging.
- [x] Quick start with one historical and one commensal example —
  docs/quickstart.md.
- [x] Scientific assumptions and prototype-derived code documented —
  docs/science/geometry_models.md, docs/limitations.md,
  docs/from-the-prototype.md, ADR-0001/0002.
- [x] No coverage/observation-ingest/candidate/database subsystem —
  boundary gate test.

## Deviations and open gates

- **VOTable**: slipped, as PRD §9.5 permits (SHOULD).
- **Covariance** (PRD open decision 1): resolved as not-propagated with
  honest labeling (ADR-0001); propagation is post-v1.
- **BLOCKING before a v1 tag** (plan §9): (1) human astrometry-aware
  review sign-off — machine review is recorded in ADR-0001/this file but
  explicitly does not discharge the science gate; (2) the release-candidate
  state committed and a green CI run on the full platform matrix for that
  commit. Until both, the version stays a release candidate.
- Benchmarks: see docs/benchmarks.md (NFR-004 representative batch).

## Independent machine review (2026-08-17)

An adversarial pre-release review agent executed the docs against the code
(every CLI command/flag, all product columns from real runs, all warning
codes, both README/quickstart snippets, the exit-code policy, the pinned
kernel checksum, and the offline gate) and independently verified all 19
test citations above. Verdict: **21 of 22 PRD §15 checkboxes satisfied with
verified evidence**; "tests pass on supported Python versions" partial
(local 3.12 only) pending the CI matrix; no scientific, boundary, or
product-contract refutation found. Findings fixed in response: the
then-missing `docs/benchmarks.md`, the undocumented
`max_motion_padding_arcsec` corridor column, and removal of the
`sgl-search-planner` prototype directory (which contained the reference
sqlite ledger).
