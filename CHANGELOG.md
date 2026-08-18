# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
