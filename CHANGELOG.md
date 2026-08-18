# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Exports and full CLI (Phase 7): ECSV (canonical, with units and table
  metadata), lossless versioned JSON (NaN → null), deterministic
  unit-suffixed CSV, and DS9 regions (corridor polylines + assumed-width
  circles, pointing circles; invalid samples omitted and counted) — all
  from the same typed result objects with no geometry imports; a provenance
  manifest with every product (science identity hashed apart from run
  metadata, output/input file checksums, library versions, conventions);
  `sglseti generate` (with `--epochs` override and `--strict`) and
  `sglseti plan` CLI commands with the documented exit policy (0 clean,
  1 completed-with-invalid-rows, 2 usage/domain errors); request
  validation now refuses DS9 output without an explicit assumed half-width
  (ADR-0001). VOTable slips per the v1 cut line.
- Observability and commensal planning (Phase 6): site context per locus
  (AltAz altitude/azimuth, Sun altitude, Moon separation — Moon added to
  the `Ephemeris` protocol and to the committed DE440s excerpt kernel),
  inclusive-threshold constraint evaluation with machine-readable failure
  codes, every-contiguous-window finding with documented middle-epoch
  representatives (no hidden "best time"), greedy adjacent circular-FOV
  grouping with separately-reported radius components (track extent,
  assumed half-width, half-exposure motion padding via `fov.exposure_s`),
  and stateless `plan_commensal()` attaching visibility and
  priority/epoch-ordered candidate pointings to a generated result —
  no ledger, no schedule.
- Epoch-neutral batch generator (Phase 5): `generate_loci(request, registry)`
  produces the deterministic targets × roles × epochs × segments product as
  `LocusSample` rows plus one `Corridor` per target/role/epoch, with
  documented stable ordering, preserved caller epoch IDs and joinable
  pass-through metadata, grid-epoch materialization (`grid-NNNNNN` IDs),
  per-combination failure isolation (invalid status rows with NaN
  coordinates and reason codes) or `strict` batch failure, honest
  uncertainty labeling (`assumed` vs `not_propagated` + warning), and
  path-independent `calculation_id`/`request_id` (ephemeris identified by
  content checksum; `EphemerisSpec.path` stripped from identities).
- Canonical ephemeris kernel and explicit fetch (ADR-0002): JPL DE440s
  pinned by SHA-256 as the canonical kernel; a committed 1.16 MB DE440s
  excerpt (Sun/EMB/Earth, 2010–2035) as the offline real-kernel regression
  fixture; `sglseti fetch ephemeris|iers` as the only network-using
  commands (atomic, checksum-verified downloads); `jpl` optional dependency
  extra for `jplephem`.
- Geometry core (Phase 4): `GeometryModel`/`Ephemeris` protocols, the
  reviewed `tusay2022_eq5_7_v1` model with SSB light-arrival catalog epochs,
  physical-event diagnostics, declared target-distance approximation, and
  machine-readable validity (`z > d/10` invalid; sub-focal, long-span, and
  missing-RV warnings); astropy ephemeris adapter (builtin + checksummed
  local JPL kernels, coverage errors, scoped offline IERS policy — no
  process-global mutation); barycentric relay projection with geometric ICRS
  line of sight; apparent CIRS/AltAz via the full barycentric-cartesian
  transform; central finite-difference motion rates; regression suite
  passing all Phase 0 reference fixtures including the double-retardation
  negative control and the Alpha Centauri published-epoch anchor.
- Sampling and provenance primitives (Phase 3): reciprocal-distance
  relay-range partitioning into deterministic `RangeSegment`s
  (`sglseti.sampling`; count, angular-step, and explicit-distance policies;
  exact endpoint bounds; no coverage semantics), versioned canonical
  serialization and stable hashing with typed serializers for
  time/quantity/enum/dataclass values and path rejection
  (`sglseti.provenance`), science-vs-run manifest builder, `request_id`,
  registry hashing unified onto the canonical schema, and the ephemeris-free
  `sglseti samples` CLI command with golden identity tests.
- Reconciled science model codification (Phase 0): v1 geometry specification
  (`docs/science/geometry_models.md`), ADR-0001 adopting
  `tusay2022_eq5_7_v1` with SSB light-arrival catalog epochs and the
  no-covariance-propagation cut line, the frozen `DirectionSolution`
  contract (dataclass + field-drift test), and reviewed reference fixtures
  under `tests/data/reference/` produced by two prototype-independent
  oracles, including the double-retardation negative control.
- Domain models and input validation (Phase 2): frozen dataclasses and enums
  for the scientific boundary (`sglseti.models`), strict curated target
  registry loading with normalized source hash and missing-radial-velocity
  policy (`sglseti.targets`), request schema v1 with exactly one time mode
  and strict-UTC ECSV/CSV epoch tables (`sglseti.config`), `sglseti validate
  targets|request` CLI commands, lazy top-level re-exports, and the
  historical/commensal example inputs.
- Package scaffold: installable `sglseti` package with `pyproject.toml`,
  `sglseti` console script, domain-error CLI boundary, typed-package marker,
  unit/integration/regression test layout, import-hygiene test (no sqlite3,
  no network, no file access at import), and CI configuration.
