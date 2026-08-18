# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Beam-crossing search (`sglseti crossings`, `find_crossings()`,
  `impact_parameter()`): finds when an observer passes closest to a
  target's hypothesized relay beam axis under the new `sun_star_axis_v1`
  contract (ADR-0003) — inbound (star→relay uplink) at the apparent-state
  epoch, outbound (relay→star downlink) at the tx aim epoch, both reusing
  the reviewed `tusay2022_eq5_7_v1` catalog propagation. A crossings
  request (crossings schema v1: targets, link directions, continuous time
  intervals with stable `interval_id` join keys, observer, representative
  relay distance, assumed beam radii, scan controls) is searched
  deterministically offline: coarse scan, golden-section closest-approach
  refinement, bisected ingress/egress per assumed radius. Products
  (`events.ecsv`/`.csv`, `windows.ecsv`/`.csv`, `result.json`,
  `manifest.json`; crossings result schema v1) report the impact parameter
  itself (AU/km/solar radii) with signed axis distance and side,
  transverse speed, the axis direction, and the star/relay pointings an
  observation would use — never a detectability verdict. Boundary minima
  are degraded and flagged (`minimum_at_interval_start/stop`), assumed
  radii are labeled hypotheses, uncertainty stays `not_propagated` with a
  warning, ephemeris-coverage failures yield invalid status rows (or fail
  the batch with `--strict`), and the crossings/event/window IDs are
  stable science-input identities. `sglseti validate crossings` and
  `examples/crossings.yaml` included.

## [1.0.0rc2] - 2026-08-17

Fixes for the scientific accuracy review.
`RESULT_SCHEMA_VERSION` bumped to 2 (new sample/pointing/visibility
columns); `tusay2022_eq5_7_v1` model version bumped to 1.1.0 (validity
semantics changed; directions unchanged).

### Changed

- The focal-distance check uses the finite-source photospheric threshold
  `z_min = f_inf·d/(d − f_inf)` instead of the source-at-infinity constant,
  and samples below it are `degraded`, not silently valid (review finding
  4; `solar_focal_min_au()` exported). The threshold remains ideal and
  geometric — practical observing limits lie farther out.
- Visibility verdicts also probe the corridor's angular extreme points
  (reported values stay the representative sample's), and pointing radii
  gained a `window_drift_arcsec` component bounding the group's motion
  across the advertised window's grid epochs (review finding 5).
- The paper's `z > d/10` probe-placement restriction is reported as a
  search prior, not model invalidity (review finding 6): such samples are
  now `degraded` with `outside_search_prior` (previously `invalid` with
  `relay_beyond_model_bound`), remain consumable, and any pointing built
  from them — or from below-focal samples — carries the condition code.
  `invalid` is reserved for uninterpretable results.

- Validity is now the authoritative gate for observing products (review
  finding 1): planning, visibility, and DS9 export consume only
  operational samples (`LocusSample.is_operational`), so a
  finite-but-invalid coordinate (e.g. beyond the `z > d/10` bound) can no
  longer enter a pointing, window, or region file; tabular exports keep
  such rows, labeled, as the diagnostic channel.
- Pointing footprints now cover the relay-distance intervals their samples
  represent (review finding 2): samples carry segment bounds
  (`z_near_au`/`z_far_au`, `q_lo_per_au`/`q_hi_per_au`), boundary
  geometric-ICRS coordinates, and near-boundary rates; the planner's zone
  center/extent/motion padding include those boundaries, and pointings
  state their covered interval (`z_near_au`/`z_far_au`).
- The IERS-A Earth-orientation table is a first-class pinned resource
  (review finding 3): `sglseti fetch iers --output-dir …` downloads it
  atomically with reported checksum and coverage; a request `iers` block
  installs that exact table via astropy's `earth_orientation_table`
  context. AltAz/CIRS transform warnings are captured into sample and
  visibility warnings (new `VisibilitySample.warnings`) with validity
  degraded — never silent; the resolved IERS identity
  (`iers_a:sha256:…`/`iers_bundled:…`) enters the calculation ID and
  manifest for requests with apparent or site products, and
  `astropy-iers-data` joined the recorded versions.

## [1.0.0rc1] - 2026-08-17

Release candidate for v1. All PRD v1 functionality is implemented and
tested (`docs/release/v1-acceptance.md`); the final 1.0.0 tag is blocked on
human astrometry-review sign-off (ADR-0001 review section) and a green CI
platform matrix. Documentation set added: quick start, conventions and
product reference, resources, limitations, from-the-prototype provenance,
acceptance status, and benchmarks; release-gate tests added
(network-blocked pinned-resource reproducibility; no-ledger/SQLite
boundary).

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
