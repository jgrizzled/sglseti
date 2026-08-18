# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0]

### Changed

- Greenfield identity baseline (2026-08-18, adopted before first
  operational use; supersedes the interim compatibility notes in the
  entries below). Canonical schema v2: dataclass fields equal to their
  declared default are omitted from identities — adding a defaulted field
  to any record can never move existing hashes (the flip side, accepted
  deliberately: changing a scientific field's DEFAULT is an
  identity-relevant change requiring a canonical schema bump) — and
  fields named `path` never enter identities; file-backed resources
  contribute pinned content checksums, which are now REQUIRED on
  spacecraft observer specs and sampled-state specs. The per-class
  `__canonical__` compatibility hooks, the observer-identity substitution
  machinery, and the ephemeris path-stripping special case are deleted in
  favor of these two generic rules. The target registry is a SINGLE
  schema (`schema_version: 2`); the v1 registry format, its dual loader,
  and the lowest-schema normalization mechanism are removed (there are no
  v1 registries to migrate). Every hash moved exactly once with the
  canonical bump; this is the frozen baseline archival consumers build
  on.

### Added

- Published accuracy budget (v1.1 roadmap item 6.12 / improvements §2.5;
  `docs/accuracy_budget.md`): the geometric-pointing error budget by
  model, observer type, epoch span, and target-state provider, separating
  declared model approximations, measured resource floors, and
  propagated input uncertainty, with scaling laws for untabulated
  configurations. Cited numbers are pinned by
  `tests/regression/test_accuracy_budget.py`: the builtin-vs-kernel
  relay-pointing floor is <= 0.02 mas (the geometry depends on the
  Earth-Sun relative vector, cancelling ~119 km of absolute analytic
  ephemeris error), the tx-epoch amplification law mu\*2d/c is verified to
  1 percent (~74 arcsec for Wolf 359), spacecraft displacement maps to
  delta/rho exactly (0.01 AU at 550 AU = 3.76 arcsec), and the neglected
  solar-motion class is bounded by v_sun/c ~ 11 mas, consistent with the
  measured Horizons light-time residual. This closes all three §2.5
  science gates.

- Spacecraft crossing verification and benchmark (v1.1 roadmap item 6.11
  / improvements §3.3, §3.4). Regression tests run the real Wolf 359
  outbound-beam scenario on the pinned DE440s kernel with tabular
  spacecraft observers (kernel Earth plus a fixed displacement) and pin
  two physical invariants of the beam-axis geometry: a displacement ALONG
  the axis leaves the crossing epoch and impact parameter unchanged
  (< 2e-6 AU / < 10 min), while a CROSS-axis displacement shifts the
  crossing by exactly its magnitude, split between `b_min` and
  `v_perp * dt` (verified to 10%). The uncertainty-aware crossing
  distribution, the observation-interval impact minimum, and the
  point-query API all compose with spacecraft observers. Benchmarks gain
  the spacecraft row: 333 vs 368 samples/s at the reference batch —
  Hermite table interpolation is not a bottleneck.

- Result schema v3 and crossings schema v2 (v1.1 roadmap item 6.10 /
  improvements §3.5). Every sample row and crossing event now identifies
  the adopted solutions behind it: target- and observer-state provider
  ID, version, and content hash (closing §2.1's final acceptance
  criterion), on valid and invalid status rows alike. Requests gain a
  first-class `intervals` time mode (§3.1): each observation interval
  materializes into labeled sample times — `<interval_id>@start|mid|stop`
  or the declared subintegration grid — and rows carry `interval_id`,
  `interval_phase`, and `interval_duration_s`. Manifests add per-owner
  provider summaries, an `uncertainty` block, declared `time_semantics`,
  and an optional caller-supplied `source_revision` alongside the
  recorded package version — run metadata, never science identity.
  `votable` joins the output formats (`samples.vot` / `events.vot` via
  astropy's built-in writer, units preserved). MOC/ST-MOC envelope
  export is deliberately deferred: coverage products belong to the survey
  consumer (improvements §5).

- `sampled_state_v1` target-state family (v1.1 roadmap item 6.9 /
  improvements §2.1): externally generated, CHECKSUMMED cartesian
  ephemerides of the endpoint itself. The registry-v2 `sampled_state`
  block requires the content checksum (identities use it, never the
  path), declares its epoch semantics (`ssb_light_arrival_time` |
  `physical_event_time` — the v1 geometry model explicitly refuses the
  latter) and its source; interpolation is declared (cubic Hermite with
  velocity columns, linear otherwise) on table machinery shared with the
  spacecraft observer family; epochs outside the tabulated span become
  invalid status rows; a load-time consistency guard rejects tables
  pointing more than 1 degree from the linearly propagated reference
  astrometry (wrong-file protection); and parameter-based Monte Carlo
  uncertainty sampling refuses sampled targets explicitly. This is the
  only family that models `planet` endpoints, closing §2.1's
  moving-endpoint gap.
- Observer-state provider families (v1.1 roadmap item 6.8 / improvements
  §2.4). The `Observer` spec (and request YAML) now selects among six
  kinds: the existing Earth center and terrestrial site, plus
  `solar_system_body` (any body the pinned planetary ephemeris serves,
  via the new `Ephemeris.body_barycentric_au`), `spacecraft_table` (a
  checksummed tabular ECSV ephemeris with declared interpolation — cubic
  Hermite when velocity columns are present, linear otherwise — and
  coverage errors outside the tabulated span), `spacecraft_spice` (a
  SPICE SPK kernel via the optional `spiceypy` dependency; geometric
  states in the SPICE J2000 frame with the ~17 mas ICRS frame bias
  declared, SPK coverage windows enforced), and `programmatic` (a
  runtime-registered state function —
  `register_programmatic_observer()` — with a caller-declared content
  identity). Calculation IDs and manifests record the path-free CONTENT
  identity of file-backed observers, never a local path, and are
  verified path-independent (see the greenfield identity baseline entry
  above for the final mechanism). Crossing searches compose with the new observers through
  the provider layer unchanged.

- Science gates, first tranche (v1.1 roadmap item 6.7 / improvements
  §2.5). Frozen Wolf 359 crossing regression: an independent no-sglseti
  oracle on the pinned DE440s excerpt kernel reproduces the Gillon,
  Burdanov & Wright 2022 outbound-beam geometry, and the +10.6 h (2015) /
  +17.0 h (2019) offsets from the paper's published crossing epochs are
  asserted as the EXPECTED result — at the published epochs the Earth
  sits 1.78 / 2.70 R_sun off-axis, outside the paper's own 1.1 R_sun
  annulus — with ~2 arcsec publication consistency on the TRAPPIST-South
  tx pointing. Frozen JPL Horizons cross-validation (one-time online
  fetch, offline tests): the pinned kernel matches DE441 barycentric
  vectors to sub-meter and the builtin analytic ephemeris to ~119 km;
  the light-time-retarded solar direction from the geocenter and the
  Green Bank site matches Horizons astrometric coordinates to
  0.002 / 0.009 mas, validating the ephemeris + observer + direction
  pipeline end-to-end, while the ~9 mas residual of the unretarded
  geometric direction is asserted as the measured scale of the
  deliberately omitted light-time term. The continuation plan for the
  remaining roadmap work is recorded as improvements-note §6 items 7-13.

- Archive-scale execution: caching, chunking, vectorization, streaming
  (v1.1 roadmap item 6.5). Identity-keyed, bounded, bit-identical
  memoization throughout the hot path: providers by target content hash,
  propagated target states per TDB epoch, scalar ephemeris body positions,
  and site GCRS offsets (`clear_provider_cache()` /
  `provider_cache_stats()` manage it) — batch generation runs ~4.3x
  faster at the reference configuration with unchanged outputs.
  `plan_calculation()` + `iter_locus_chunks()` expose deterministic
  chunked execution: one corridor per target/role/epoch in the documented
  product order, sliceable by chunk index with unchanged identities
  (`generate_loci()` is now built on the same path). Providers gain
  vectorized `states_at()` (one `apply_space_motion` for many epochs,
  elementwise bit-identical, ~85x) and observers `positions_au()`.
  `write_samples_stream()` writes `samples.csv` row-by-row
  (byte-identical to the batch writer) plus bounded ECSV parts from the
  chunk stream, so exports never materialize the full sample table.
  Benchmarks: `benchmarks/archive_scale.py`; measurements in
  `docs/benchmarks.md`.

- Propagated uncertainty and uncertainty-aware crossings (v1.1 roadmap
  item 6.4; `sglseti.uncertainty`, plus
  `sglseti.crossings.minimize_impact_parameter`). Seeded Monte Carlo
  propagation of registry-v2 target uncertainties:
  `target_uncertainty()` assembles the sampling covariance from per-value
  uncertainties and covariance/correlation matrices with exact unit
  validation (Gaia tangent-plane convention); `draw_target_samples()`
  draws fully validated perturbed targets, rejecting domain-violating
  draws (the explicit non-Gaussian treatment — orbital elements pass
  through Kepler's equation to empirical percentiles);
  `propagate_locus_uncertainty()` reports the nominal direction,
  per-sample sky offsets for region construction, a declared confidence
  level with its empirical confidence radius, sky covariance,
  along/cross-track sigmas, explicit contribution labels (target state
  propagated; observer state, ephemeris, and model floors declared
  not-propagated), and surfaced degraded/invalid sample counts;
  `crossing_uncertainty()` re-minimizes the impact parameter per sample
  in a window around a nominal crossing event, yielding empirical bounds
  and sigmas on `b_min`, closest-approach time, and transverse speed,
  plus side-of-axis stability, with window-edge minima degrading the
  product explicitly. `minimize_impact_parameter()` minimizes `b(t)` over
  an `ObservationInterval` for schedule joins without a multi-year scan.
  Every propagated product records seed, sample count, and confidence
  level, and carries `UncertaintyMethod.PROPAGATED` — structurally
  distinct from an assumed search pad.

- Observation intervals and the continuous/adaptive locus API (v1.1
  roadmap item 6.3; `sglseti.locus`). `ObservationInterval` makes an
  archival observation a first-class span (start/midpoint/stop, duration,
  optional subintegration cadence, pass-through metadata) while point
  epochs stay fully supported. `evaluate_locus()` exposes the continuous
  mapping `(target, role, observation time, observer, z) -> direction`;
  `adaptive_locus()` returns an ordered, z-mapped polyline whose angular
  deviation from the continuous locus is bounded by a caller-selected
  tolerance (probe-accepted at half tolerance; budget exhaustion attaches
  an explicit warning, and the achieved probe deviation is recorded);
  `swept_locus()` builds a conservative swept envelope over an
  observation interval with a declared `envelope_pad_arcsec`;
  `covered_z_intervals()` refines an opaque caller-supplied
  `contains(ra_deg, dec_deg)` footprint test into covered relay-distance
  intervals with verified-covered endpoints — archive footprint schemas
  never enter the package; and `interval_states()` reports position and
  motion rates at an interval's representative or subintegration times.

- Target registry schema v2 and orbital target-state families (v1.1
  roadmap item 6.2). Schema v2 (`docs/registry.md`,
  `examples/targets_v2.yaml`) adds explicit target-state provider
  selection, immutable catalog/literature identifiers with release
  versions, per-value provenance with 1-sigma uncertainties and mandatory
  units, full covariance/correlation matrices with a declared parameter
  ordering, and `quality` / `model_rationale` metadata. Two new provider
  families implement motion the linear baseline refuses:
  `acceleration_astrometry_v1` (catalog quadratic proper-motion terms)
  and `two_body_orbit_v1` (resolved components and system barycenters
  from a published Campbell orbit about a linearly propagating
  barycenter, with declared approximations). Registry validation is
  provider-aware: `accelerating_system` / `unresolved_binary` flags stay
  errors for linear targets but are accepted by the richer families, and
  orbit/endpoint coherence is enforced. (The v1 schema and its
  migration path were later removed by the greenfield decision above;
  the registry has a single schema.) The `two_body_orbit_v1` family is
  verified against the published Alpha Centauri AB (Pourbaix & Boffin 2016) and Sirius AB (Bond et al. 2017) solutions via an independent
  Thiele-Innes/bisection reference implementation
  (`tests/data/reference/two_body_orbit_reference.py`), including the
  observed ~4 arcsec Alpha Cen separation in 2016 and ~11 arcsec Sirius
  maximum near the 2019.64 apastron.

- Target-state and observer-state provider protocols
  (`sglseti.providers`; v1.1 roadmap item 6.1). `TargetStateProvider`
  and `ObserverStateProvider` define versioned, metadata-declaring
  interfaces (epoch semantics, frame, origin, validity interval /
  coverage, uncertainty / interpolation policy, and path-independent
  content identity) behind which richer endpoint and observer models can
  be added without touching the geometry core. Baseline families
  `linear_astrometry_v1`, `earth_center_v1`, and `terrestrial_site_v1`
  reproduce the previous inline behavior exactly — the geometry core now
  consumes catalog propagation and observer positions through
  `resolve_target_state_provider()` / `resolve_observer_state_provider()`,
  and all existing fixtures are numerically unchanged. The
  `tusay2022_eq5_7_v1` model additionally rejects providers whose epoch
  semantics are not SSB light-arrival indexed.

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
