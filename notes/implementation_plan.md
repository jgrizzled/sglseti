---
title: "SGLSETI v1 Implementation Plan"
date: 2026-08-17
status: "Draft implementation plan v0.2"
inputs:
  - notes/sglseti_python_package_prd.md
  - notes/seti_strategies_for_sgl_technosignatures.md
  - notes/sgl_light_time_epoch_reconciliation.md
  - sgl-search-planner/
---

# SGLSETI v1 Implementation Plan

## 1. Outcome

Build a new `sglseti` package that uses one stateless, epoch-neutral engine to generate:

- historical SGL target loci for external archive cross-reference; and
- current/future loci, visibility windows, and simple circular-FOV pointings for external commensal-search systems.

The implementation should reuse tested ideas and selected code from `sgl-search-planner`, but it should not preserve that prototype's observation-ledger architecture. No observation ingest, completion tracking, historical-coverage calculation, candidate tracking, or SQLite subsystem belongs in this package.

The primary deliverables are:

1. an installable `src/sglseti` Python package;
2. a typed Python API;
3. a thin `sglseti` CLI;
4. ECSV, JSON, CSV, DS9, and provenance-manifest outputs;
5. historical and commensal examples; and
6. a reviewed geometry specification with regression fixtures.

---

## 2. Decisions carried into implementation

These are implementation decisions, not open-ended design tasks:

1. **Start a new package.** Do not rename the prototype directory in place. Port selected code into a clean `src/sglseti` layout so ledger assumptions do not leak into the public API.
2. **Use one generator for all epochs.** Historical and commensal behavior differ only in input form and optional planning context.
3. **Keep the core stateless.** Inputs are immutable domain objects; results are returned in memory and optionally written to files.
4. **Keep a curated YAML target registry.** The registry is source data, not a service-backed catalog or SQLite database.
5. **Use Astropy and NumPy first.** Retain the prototype's small dependency footprint until validation demonstrates a need for direct SPICE or SciPy.
6. **Use `argparse` for v1.** The prototype already has an adequate error-handling pattern; a CLI framework migration would add little product value.
7. **Retain reciprocal-distance sampling.** It is a useful physical-to-angular abstraction even without a coverage ledger.
8. **Do not call assumed padding “uncertainty.”** A configured corridor half-width and propagated catalog covariance are different fields and methods.
9. **Adopt the reconciled v1 geometry model.** Ship the initial role calculation as `tusay2022_eq5_7_v1`, distinguish SSB light-arrival catalog epochs from physical target-event epochs, and expose its approximations.
10. **Make network access opt-in and separate.** Target calculation defaults to no implicit IERS, catalog, kernel, or name-resolver downloads.

---

## 3. Prototype assessment

The prototype is approximately 2,000 lines and proves several useful product choices:

- frozen, target-list-driven inputs;
- linear stellar-space-motion propagation with Astropy;
- a role-aware local-relay calculation;
- topocentric geometry and basic observing context;
- reciprocal-distance partitioning;
- conservative circular-FOV grouping;
- deterministic hashes and IDs;
- CSV, DS9, and JSON-manifest output; and
- a small CLI with clear configuration errors.

It also couples target planning to a campaign profile and SQLite ledger. That coupling should be removed rather than abstracted into v1.

### 3.1 Reuse matrix

| Prototype source | Decision | How to use it in `sglseti` |
|---|---|---|
| [`sgl_search/config.py`](../sgl-search-planner/sgl_search/config.py) | Refactor and port | Reuse strict YAML-loading and small immutable-record patterns. Split target, observer, request, instrument, and constraints into independent domain types. Remove `Profile` and all completion/cadence fields. |
| [`sgl_search/geometry.py`](../sgl-search-planner/sgl_search/geometry.py) | Port with scientific refactor | Reuse target-to-`SkyCoord`, Solar/observer state, relay-vector, apparent-coordinate, environment, and finite-difference-rate techniques. Preserve the reviewed Tusay offsets, but replace the private epoch helper with an explicit `tusay2022_eq5_7_v1` solution and diagnostics. |
| [`sgl_search/partition.py`](../sgl-search-planner/sgl_search/partition.py) | Port with renaming | Preserve reciprocal-distance math and deterministic ordering. Rename coverage-oriented `SearchCell` to `RangeSegment` or `RelaySample`; remove completion semantics. |
| [`sgl_search/planner.py`](../sgl-search-planner/sgl_search/planner.py) | Extract selected functions | Reuse time-grid construction, constraint evaluation, zone sizing, and greedy adjacent grouping. Rewrite `plan()` so it consumes generated loci and never opens a ledger. |
| [`sgl_search/output.py`](../sgl-search-planner/sgl_search/output.py) | Port and generalize | Retain deterministic CSV field ordering and DS9 syntax. Remove the observation-results template. Add ECSV and lossless JSON from shared result records. |
| [`sgl_search/cli.py`](../sgl-search-planner/sgl_search/cli.py) | Rebuild around reusable shell | Retain the `argparse`/domain-error boundary. Replace `cells`, ledger-backed `plan`, `coverage`, `ingest`, and `report` with `validate`, `samples`, `generate`, and stateless `plan`. |
| [`sgl_search/catalog.py`](../sgl-search-planner/sgl_search/catalog.py) | Optional, late | A one-object SIMBAD draft helper may be retained as an extra. Do not make it part of calculation or trust its hard-coded reference epoch without validation. |
| [`sgl_search/ledger.py`](../sgl-search-planner/sgl_search/ledger.py) | Do not port | Move or copy concepts only if the separate historical-coverage project needs them. `sglseti` must not import this module. |
| [`examples/targets.yaml`](../sgl-search-planner/examples/targets.yaml) | Adapt | Keep Barnard's Star as a high-proper-motion example, add endpoint kind and stronger source/provenance fields, and mark all sample values as non-operational. |
| [`examples/campaign.yaml`](../sgl-search-planner/examples/campaign.yaml) | Split | Produce a geometry request plus separate historical-epoch and commensal-night examples. Delete `profile` and visit-completion settings. |
| Prototype tests | Selectively rewrite | Preserve reciprocal-range properties and hash intent. Replace the geometry smoke test with reference values; do not port ledger tests. |

### 3.2 Specific reusable symbols

The following prototype code is the starting point, not an immutable API:

- `config.load_yaml()` and `ConfigError` in `config.py` lines 10–47;
- `TargetAstrometry`, `Target`, and `Site` in `config.py` lines 50–100;
- the target-registry checks in `load_targets()` in `config.py` lines 169–210;
- `GeometryEngine.target_coord()` and `_target_unit_from_sun()` in `geometry.py` lines 87–117;
- the relay and observer vector construction in `GeometryEngine.probe_point()` in `geometry.py` lines 132–188;
- `GeometryEngine.environment()` and `motion_rates()` in `geometry.py` lines 190–226;
- `SearchCell`, `_partition_id()`, and `generate_cells()` in `partition.py` lines 14–102;
- `_time_grid()` and `_find_best_time()` in `planner.py` lines 96–158;
- `_zone_for_cells()` and `_group_cells()` in `planner.py` lines 161–242;
- `_stable_hash()` in `planner.py` lines 71–75;
- the CSV and DS9 patterns in `output.py` lines 12–127; and
- `build_parser()`/`main()` in `cli.py` lines 194–249.

### 3.3 Code that must not be copied as-is

1. `GeometryEngine._direction_epoch()` in [`geometry.py`](../sgl-search-planner/sgl_search/geometry.py) lines 119–130 uses:

   ```text
   receiver    -> observation time - 2z/c
   transmitter -> observation time + 2d/c
   ```

   These offsets match Tusay et al. equations 6 and 7 when `apply_space_motion()` is understood to propagate an arrival-indexed catalog direction. For Rx, \(t_o-2z/c\) is the approximate SSB-arrival/catalog epoch; the corresponding physical emission epoch is \(t_o-(2z+d)/c\). The prototype helper must still be refactored because it hides this distinction, returns no physical-event diagnostics, assumes \(\rho=z\), and does not version the model. See [SGL Rx/Tx Light-Time Epoch Reconciliation](sgl_light_time_epoch_reconciliation.md).

2. `GeometryEngine.__init__()` mutates Astropy's process-global `iers.conf.auto_download`. Replace that with an explicit resource policy/context and default it to offline.

3. `probe_point()` adds a GCRS site-position vector directly to the Earth's barycentric vector. Confirm frame compatibility and numerical tolerance independently before retaining this calculation.

4. `probe_icrs.transform_to(CIRS(...))` treats the finite-distance relay as an ICRS coordinate. Validate the resulting apparent direction against an independent construction; do not assume the transform semantics are correct merely because values are finite.

5. `load_targets()` permits `source: unspecified` and does not explicitly reject non-finite numeric values. V1 science inputs require real provenance and finite-value checks.

6. `Campaign` mixes geometry, telescope, signal-search profile, and completion policy. V1 must not retain this aggregate type.

7. `plan()` opens a ledger, removes completed cells, and puts profile fields on every tile. The new planner receives a complete set of requested segments and returns all eligible pointings.

8. `write_all()` emits an observation-results template. The new writer emits only target/corridor/pointing data and provenance.

9. The current geometry smoke test checks only that a coordinate is finite. It provides no scientific expected value and is insufficient as a regression oracle.

10. The SIMBAD helper hard-codes J2000 as the reference epoch. If retained, it must obtain or explicitly require the epoch and continue to label output unvetted.

---

## 4. Target architecture

```text
src/sglseti/
├── __init__.py
├── models.py
├── config.py
├── targets.py
├── ephemeris.py
├── geometry.py
├── sampling.py
├── generate.py
├── observability.py
├── planning.py
├── provenance.py
├── export.py
└── cli.py
```

### 4.1 Dependency direction

```text
models       sampling       provenance
   |             |               |
targets      geometry <--- ephemeris
   \             |             /
    \-------- generate --------/
                  |
          observability
                  |
              planning
                  |
               export
                  |
                 CLI
```

Rules:

- `models.py` imports no application module.
- `geometry.py` does not read YAML or write files.
- `generate.py` does not know whether an epoch is historical or future.
- `planning.py` does not know about archived observations or completion state.
- exporters never recalculate geometry.
- CLI commands only parse arguments, call public functions, write results, and format errors.

### 4.2 Core domain objects

Use frozen dataclasses and Astropy `Quantity`/`Time` at the public scientific boundary.

| Object | Purpose |
|---|---|
| `AstrometricState` | ICRS position, parallax/distance, proper motion, radial velocity, reference epoch and scale, optional covariance, source |
| `Target` | stable ID, display name, endpoint kind, astrometric state, flags and metadata |
| `TargetRegistry` | immutable mapping plus normalized source hash |
| `Observer` | Earth center or fixed geodetic site with stable ID |
| `EphemerisSpec` | adapter name, resource identity, checksum, and allowed coverage |
| `RelayRange` | near/far distances and sampling policy |
| `RangeSegment` | deterministic reciprocal-distance bounds and ID |
| `Epoch` | stable caller ID plus typed time and pass-through metadata |
| `GeometryRequest` | targets, roles, epochs, observer, model, range, requested products |
| `LocusSample` | one computed coordinate and its diagnostics/status |
| `Corridor` | ordered samples and width metadata at one target/role/epoch |
| `VisibilitySample` | site-dependent context and constraint results |
| `Pointing` | conservative circular zone over adjacent range segments |
| `CalculationResult` | immutable collection plus provenance and warnings |

### 4.3 Geometry protocol

Define a small protocol before implementing models:

```python
class GeometryModel(Protocol):
    model_id: str
    model_version: str

    def target_direction(
        self,
        target: Target,
        observation_time: Time,
        relay_distance: Quantity,
        role: Role,
        ephemeris: Ephemeris,
    ) -> DirectionSolution: ...
```

`DirectionSolution` should expose:

- the observer reception epoch;
- the catalog direction epoch with `ssb_light_arrival_time` semantics;
- approximate relay, Solar-lens, and physical target-event epochs;
- physical target-event kind;
- target, Sun–relay, and approximate observer–relay light times;
- the propagated target direction;
- model ID and status; and
- approximation flags, including \(\rho=z\), constant \(d\), linear stellar motion, and neglected Solar motion during local light travel.

Relay placement and observer projection can then be shared across role models.

Do not hide the role epoch inside a private helper as the prototype does; it is part of the scientific result.

### 4.4 Stable identity model

Use a versioned canonical JSON serializer with:

- sorted mapping keys;
- explicit unit/value pairs;
- normalized UTC/TDB time representation;
- finite floats only;
- stable list ordering;
- resource content hashes rather than absolute paths; and
- a serializer/schema version in the hash payload.

Define separate IDs:

- `request_id`: all normalized user science inputs;
- `segment_id`: target + role + physical range partition;
- `sample_id`: segment or explicit distance sample;
- `calculation_id`: request + model + target source + ephemeris resources;
- `corridor_id`: calculation + epoch + target + role; and
- `pointing_id`: corridor(s) + grouping/FOV settings.

The generation timestamp appears in the manifest but never changes these IDs.

---

## 5. Work plan

### Phase 0 — Codify the reconciled science model

**Goal:** turn the resolved epoch convention into an independently reviewable implementation contract before porting geometry code.

The source derivation is [SGL Rx/Tx Light-Time Epoch Reconciliation](sgl_light_time_epoch_reconciliation.md). Its central decision is:

    model:    tusay2022_eq5_7_v1
    antipode: u = t_o
    rx:       u = t_o - 2z/c
    tx:       u = t_o + 2d/c

Here \(u\) is the SSB light-arrival epoch used for catalog propagation, not the physical target-event epoch.

Tasks:

1. Write the package science specification and architecture decision record from the reconciliation note.
2. Have an astrometry-aware reviewer independently verify:
   - the event ordering and signs;
   - the distinction between physical event time and catalog arrival epoch;
   - the \(\rho\simeq z\) reduction; and
   - the interpretation of Astropy/ERFA space-motion propagation.
3. Freeze the `DirectionSolution` fields and approximation flags before geometry migration.
4. Define reviewed numerical fixtures:
   - a static synthetic target;
   - a constant-velocity target evaluated through both physical-state and catalog-arrival formulations;
   - a deliberately double-retarded negative case;
   - Barnard's Star for a high-proper-motion scale/sign check; and
   - one published Alpha Centauri epoch.
5. Decide the v1 covariance cut line:
   - preferred: propagate catalog covariance; or
   - minimum acceptable: retain covariance, label it unpropagated, and require explicit assumed padding for region output.
6. Set model-validity bounds and preliminary numerical tolerances, including the \(\rho=z\) and neglected-Solar-motion diagnostics.

Artifacts:

- `docs/science/geometry_models.md`;
- `docs/adr/0001-v1-geometry-model.md`; and
- reviewed fixture definitions under `tests/data/reference/`.

Exit criteria:

- a scientific reviewer approves the role event table and catalog-epoch convention;
- expected role epochs and directions exist independently of the prototype code;
- the negative fixture detects an extra Rx \(-d/c\); and
- no unresolved epoch-semantic ambiguity blocks implementation.

### Phase 1 — Scaffold the new package

**Goal:** create an isolated, installable foundation with CI and no ledger dependencies.

Tasks:

1. Add `pyproject.toml` with a `src/` layout and package name `sglseti`.
2. Support maintained Python versions chosen at implementation time.
3. Add core dependencies: NumPy, Astropy, and PyYAML.
4. Add test and lint/type-check development groups using repository conventions.
5. Add the `sglseti` console script mapped to `sglseti.cli:main`.
6. Add unit, integration, regression, and test-data directories.
7. Add a test that importing `sglseti` does not import `sqlite3`, open files, or initiate network access.
8. Add license, README skeleton, changelog, and contributor instructions.

Reuse:

- base project metadata and console-script pattern from [`pyproject.toml`](../sgl-search-planner/pyproject.toml);
- error-return structure from `sgl_search.cli.main()`.

Do not reuse:

- the `sgl-search-planner` distribution name;
- package-level ledger dependencies or CLI wording; or
- optional dependencies not needed by a committed v1 feature.

Exit criteria:

- `python -m pip install -e .` works in a clean environment;
- `sglseti --help` works; and
- an empty test suite runs in CI on supported platforms.

### Phase 2 — Implement domain models and input validation

**Goal:** establish the stable scientific boundary before porting orchestration.

Tasks:

1. Implement the domain objects in section 4.2 as frozen dataclasses.
2. Implement explicit enum/literal types for role, endpoint kind, validity, uncertainty method, and correction type.
3. Port and strengthen `load_yaml()` and target validation.
4. Require finite numbers, positive parallax or explicit distance, valid RA/Dec, an explicit frame/epoch, and a non-empty source.
5. Treat missing radial velocity as either:
   - a validation error under strict mode; or
   - a flagged prior/value supplied explicitly by the request.
6. Reject unsupported binary/component ambiguity based on `endpoint_kind` and flags.
7. Define request schema v1 with exactly one time mode.
8. Implement ECSV/CSV epoch-list parsing with stable `epoch_id` and strict UTC behavior.
9. Split the prototype campaign example into:
   - `examples/targets.yaml`;
   - `examples/historical.yaml`;
   - `examples/historical_epochs.ecsv`; and
   - `examples/commensal-night.yaml`.
10. Implement `sglseti validate targets` and `sglseti validate request`.

Reuse:

- `ConfigError`, `_number()`, `_integer()`, `load_yaml()`, `TargetAstrometry`, `Target`, `Site`, and the useful validation branches from [`config.py`](../sgl-search-planner/sgl_search/config.py).

Refactor:

- use Astropy units/time in domain objects while keeping explicitly suffixed scalar fields in YAML;
- remove `Night`, `Instrument`, and `Constraints` from one monolithic `Campaign` loader;
- remove `Profile`, `required_successful_visits`, `min_visit_separation_days`, `min_quality`, and `include_invisible` from geometry requests.

Tests:

- schema-version mismatch;
- non-mapping/empty registry;
- NaN/infinite values;
- invalid coordinate/range/site bounds;
- missing source/epoch/radial velocity policy;
- duplicate target/epoch IDs;
- ambiguous timestamps; and
- normalized round trip.

Exit criteria:

- both example request types validate without computing geometry;
- every invalid input fails with a path-specific message; and
- domain models contain no persistence or archive concepts.

### Phase 3 — Implement sampling and provenance primitives

**Goal:** port the most self-contained, already-tested prototype concepts first.

Tasks:

1. Port reciprocal-distance partitioning from [`partition.py`](../sgl-search-planner/sgl_search/partition.py).
2. Rename `SearchCell` to `RangeSegment` and coverage-flavored fields accordingly.
3. Support either an explicit sample list, a fixed segment count, or a reciprocal-distance angular step.
4. Preserve exact near/far bounds and deterministic ordering.
5. Decide whether include/exclude segment filters are necessary for v1; omit them unless a real commensal use case needs them.
6. Implement canonical JSON serialization and stable hashing in `provenance.py`.
7. Replace the prototype's `_stable_hash(default=str)` behavior with explicit serializers for quantities, time, enums, paths/resources, and dataclasses.
8. Add a manifest builder that separates deterministic science identity from run metadata.
9. Implement `sglseti samples` without importing geometry-heavy modules where practical.

Reuse:

- reciprocal-distance equations, range coverage, partition hash intent, and property tests from [`partition.py`](../sgl-search-planner/sgl_search/partition.py) and [`test_partition.py`](../sgl-search-planner/tests/test_partition.py);
- SHA-256 and canonical-key ordering idea from `planner._stable_hash()`.

Tests:

- no gaps/overlap beyond floating tolerance;
- near/far ordering;
- one-cell boundary;
- deterministic IDs across runs and working directories;
- unit-normalization equivalence such as AU versus km;
- hash changes for every scientific input change; and
- hash does not change with output path or generation time.

Exit criteria:

- sample tables and IDs can be generated without an ephemeris;
- hash format has a documented schema version; and
- golden identity tests pass.

### Phase 4 — Port and validate the geometry core

**Goal:** produce scientifically labeled locus samples with no planning or export coupling.

Tasks:

1. Implement the `GeometryModel` and `Ephemeris` protocols.
2. Implement an Astropy ephemeris adapter with:
   - built-in mode for exploration;
   - local JPL file support where available;
   - resource identity/checksum capture;
   - explicit date-coverage errors; and
   - no implicit downloads.
3. Port `target_coord()` and linear `apply_space_motion()` handling while preserving each catalog's declared reference epoch and time scale.
4. Implement `tusay2022_eq5_7_v1` exactly:
   - `antipode` catalog epoch \(u=t_o\);
   - `rx` catalog epoch \(u=t_o-2z/c\), with physical emission diagnostic \(t_o-(2z+d)/c\);
   - `tx` catalog epoch \(u=t_o+2d/c\), with physical arrival diagnostic \(t_o+d/c\); and
   - `catalog_epoch_semantics=ssb_light_arrival_time`.
5. Port the Solar position, relay position, observer projection, and geometric ICRS construction after frame review.
6. Implement Earth-center first, then fixed terrestrial sites.
7. Add apparent CIRS and AltAz only after independent coordinate checks pass.
8. Expose every `DirectionSolution` epoch, light time, target-event kind, target direction, Solar/relay/observer vector, approximation flag, status, and warning on the result.
9. Compute finite-difference angular rates using configurable, recorded intervals.
10. Implement explicit assumed-width fields and the chosen v1 covariance behavior.

Reuse:

- the structure of `ProbePoint` and `EnvironmentAtPoint` from [`geometry.py`](../sgl-search-planner/sgl_search/geometry.py);
- Astropy `SkyCoord`, `Distance`, `apply_space_motion`, `get_body_barycentric`, `EarthLocation`, CIRS, and AltAz call patterns;
- the first-order `probe_xyz = sun_xyz - z * unit` relation; and
- `spherical_offsets_to()` for rates.

Required changes:

- import core Astropy dependencies normally rather than hiding them behind `_imports()`;
- avoid mutable process-global resource policy;
- use explicit unit-bearing vectors or rigorously documented array units;
- return status records rather than unstructured `ValueError` for scientifically degraded cases; and
- never reuse prototype numerical output as the only expected result.

Tests:

- analytic synthetic geometry;
- target propagation against direct Astropy calls;
- direct reproduction of Tusay et al. equations 5–7;
- physical-state/catalog-arrival equivalence for a constant-velocity target;
- a no-double-retardation negative test for Rx;
- observer-vector/frame consistency;
- published and independently calculated fixtures;
- Rx/Tx distinction and zero-motion limiting behavior;
- Earth-center/topocentric parallax;
- rate convergence under smaller finite-difference steps;
- resource coverage failure; and
- offline behavior.

Exit criteria:

- the three v1 roles pass reviewed regression tolerances;
- every sample has explicit frame/origin/time/model metadata; and
- there are no file writes, CLI calls, or planning rules in geometry code.

### Phase 5 — Build the epoch-neutral batch generator

**Goal:** make historical target generation complete before adding optional commensal conveniences.

Tasks:

1. Implement `generate_loci(request) -> CalculationResult`.
2. Form the deterministic product over targets × roles × epochs × relay samples.
3. Preserve epoch IDs and pass-through input metadata.
4. Use stable, documented output ordering.
5. Aggregate samples into one corridor per target/role/epoch.
6. Collect warnings without losing valid rows from unrelated combinations.
7. Support a strict mode that fails the batch on any invalid result and a default mode that emits status rows plus a nonzero CLI summary policy.
8. Bound memory by processing chunks while preserving deterministic output order.
9. Add the historical example and a join-back demonstration using `epoch_id`.

Reuse:

- the prototype's deterministic iteration and grouping-by-target/role ideas in [`planner.py`](../sgl-search-planner/sgl_search/planner.py), but not its ledger filtering or `PlanResult` counters.

Tests:

- single versus batch numerical equivalence;
- historical and future timestamps in one input list;
- missing/invalid target isolation;
- deterministic order under mapping/input reorder;
- exact preservation of epoch IDs; and
- representative performance fixture.

Exit criteria:

- UC1, UC2, UC4, and UC5 work through the Python API; and
- generated data contain no statements about observations or completed search space.

### Phase 6 — Implement observability and simple commensal planning

**Goal:** add site-aware, future-facing products without building a scheduler.

Tasks:

1. Port time-grid construction from `planner._time_grid()` using typed `Time`/`TimeDelta`.
2. Port the altitude, Sun-altitude, and Moon-separation calculations.
3. Replace `_find_best_time()` with a public function that returns every contiguous valid window plus a documented representative time.
4. Port `_zone_for_cells()` and `_group_cells()` using `RangeSegment` and `Corridor` inputs.
5. Preserve the conservative radius components separately:
   - sampled range-track extent;
   - assumed/model width;
   - statistically propagated width, if supported; and
   - half-exposure motion padding.
6. Support circular FOVs only in v1 and reject other shapes clearly.
7. Return pointings in priority/epoch order but do not assign a conflict-free sequence.
8. Make observability optional so historical batch generation does not pay for Sun/Moon calculations unnecessarily.

Reuse:

- `GeometryEngine.environment()` from [`geometry.py`](../sgl-search-planner/sgl_search/geometry.py);
- `_time_grid()`, `_find_best_time()`, `_zone_for_cells()`, and `_group_cells()` from [`planner.py`](../sgl-search-planner/sgl_search/planner.py);
- `Instrument.usable_radius_arcsec` from [`config.py`](../sgl-search-planner/sgl_search/config.py).

Required changes:

- no ledger argument;
- no profile, band, signal class, visit, completion, or quality fields;
- no single “best time” that hides disjoint valid windows;
- no implicit IERS network access; and
- no claim that a pointing is a scheduled exposure.

Tests:

- grid endpoints and cadence;
- visibility threshold boundaries;
- multiple disjoint windows;
- never-visible target;
- a segment too large for the usable FOV;
- adjacent grouping order;
- motion padding; and
- no geometry recomputation in exporters.

Exit criteria:

- UC3 works through the Python API; and
- a generated plan is a complete stateless function of its request and resources.

### Phase 7 — Implement exports and CLI

**Goal:** make the API usable by archive researchers and commensal integrations.

Tasks:

1. Implement ECSV as the canonical tabular output with units and metadata.
2. Implement lossless JSON using a versioned schema.
3. Port CSV output with explicit unit suffixes and deterministic columns.
4. Port DS9 circle/line output for corridors and pointings.
5. Implement manifest output for every file-producing command.
6. Add optional VOTable only after required formats pass round-trip tests.
7. Build CLI commands:
   - `validate targets`;
   - `validate request`;
   - `samples`;
   - `generate`; and
   - `plan`.
8. Reuse the prototype's concise domain-error handling and exit code `2` for invalid user input.
9. Ensure `--help` explains that archive lookup and overlap/completion tracking occur elsewhere.
10. Delete or decline to port the prototype observation-results template.

Reuse:

- `CSV_FIELDS`, row flattening, and `csv.DictWriter` approach in [`output.py`](../sgl-search-planner/sgl_search/output.py);
- DS9 header, `circle`, and `line` syntax in the same file;
- `argparse` subparser and `main()` error boundary in [`cli.py`](../sgl-search-planner/sgl_search/cli.py).

Tests:

- ECSV unit/metadata round trip;
- JSON-schema validation and round trip;
- stable CSV header/order;
- DS9 syntax fixture;
- manifest/file cross-reference;
- CLI success and invalid-input exit codes;
- CLI outputs equal direct API outputs; and
- help text contains no ledger workflow.

Exit criteria:

- all required PRD CLI examples run; and
- products can be consumed without importing internal package modules.

### Phase 8 — Documentation, review, and v1 release

**Goal:** prove the package is useful and scientifically honest at the narrowed scope.

Tasks:

1. Write a quick start with one historical and one commensal workflow.
2. Document all coordinate frames, origins, time scales, role epochs, corrections, and output columns.
3. Document local ephemeris/IERS setup and reproduce it in a network-disabled test.
4. Add a “from the prototype” note identifying ported algorithms and material changes.
5. Add a limitations page covering linear motion, binaries, assumed widths, approximate light time, circular FOVs, and lack of scheduling.
6. Benchmark the PRD's representative batch and record results.
7. Run independent astrometry/science review and resolve findings.
8. Verify the repository contains no `coverage`, `ledger`, observation-ingest, candidate, or SQLite implementation under `src/sglseti`.
9. Produce a release candidate, run the full supported-platform matrix, and tag v1 only after all PRD acceptance criteria pass.

Exit criteria:

- every checkbox in PRD section 15 is satisfied or explicitly moved out of the release with a PRD revision;
- reference fixtures have human-readable derivations/citations;
- the two example workflows run offline from a clean checkout; and
- release artifacts contain source, tests, docs, and checksums.

---

## 6. Test strategy

### 6.1 Test layers

| Layer | Purpose | Network policy |
|---|---|---|
| unit | validation, sampling, IDs, pure vector math | forbidden |
| integration | Astropy frames/time/site/ephemeris and file formats | forbidden; local fixtures only |
| regression | reviewed historical/future coordinates | forbidden; pinned resources |
| optional external validation | compare against Horizons or live catalog service | explicit marker; never in default CI |
| CLI | end-to-end examples and errors | forbidden |

### 6.2 Minimum regression matrix

| Dimension | Required cases |
|---|---|
| time | historical, present-like fixed fixture, future |
| observer | Earth center, one terrestrial site |
| target motion | zero synthetic, ordinary, high proper motion |
| role | antipode, rx, tx |
| range | near bound, midpoint, far bound, multi-segment corridor |
| coordinate | geometric ICRS, CIRS, AltAz |
| resource | built-in exploratory, pinned local ephemeris |
| status | valid, degraded, invalid/out of resource coverage |
| workflow | listed epochs, regular time grid, circular-FOV plan |

### 6.3 Prototype tests to carry forward

- Rewrite [`test_partition.py`](../sgl-search-planner/tests/test_partition.py) against `RangeSegment` and add unit-normalization and hash-schema cases.
- Reuse the intent of [`test_model_hash.py`](../sgl-search-planner/tests/test_model_hash.py): a scientific width/model change must change identity. Expand it so non-scientific paths/timestamps do not.
- Replace [`test_geometry_optional.py`](../sgl-search-planner/tests/test_geometry_optional.py) with numerical reference assertions, explicit frames, and tolerances.
- Do not port [`test_ledger.py`](../sgl-search-planner/tests/test_ledger.py); it belongs with the separate coverage project if still useful.

---

## 7. Delivery order and parallelism

The dependency-critical sequence is:

```text
Phase 0 scientific model
          |
Phase 1 scaffold
          |
Phase 2 domain/input ------ Phase 3 sampling/provenance
          \                 /
           Phase 4 geometry
                  |
           Phase 5 generator
             /           \
Phase 6 planning     Phase 7 exports/CLI
             \           /
              Phase 8 release
```

After the Phase 2 domain interfaces are stable, sampling/provenance and geometry-fixture work can proceed independently. After `CalculationResult` is stable in Phase 5, commensal planning and exporters can proceed independently.

Avoid parallel edits to the core dataclasses or JSON schema without an agreed interface change; those types affect every downstream phase.

---

## 8. V1 cut line

### Must ship

- strict curated-target and request inputs;
- exact historical epoch lists with stable join keys;
- arbitrary fixed current/future epochs and time grids;
- reviewed `tusay2022_eq5_7_v1` roles `antipode`, `rx`, and `tx`;
- distinct catalog-direction and approximate physical-event epoch diagnostics;
- relay-range corridors with reciprocal-distance sampling;
- Earth-center and terrestrial-site geometry;
- geometric ICRS output and model/provenance diagnostics;
- current/future rates and simple visibility;
- circular-FOV grouping;
- ECSV, JSON, CSV, DS9, and manifest outputs;
- Python API, CLI, offline tests, and reviewed regression fixtures.

### May slip without changing the product boundary

- VOTable output;
- optional single-object SIMBAD helper;
- full catalog-covariance propagation, only if the schema and warnings honestly mark it unpropagated and an explicit assumed width is required for region generation;
- performance optimizations beyond the stated laptop-scale requirement.

### Explicitly defer

- archive clients and footprint cross-matching;
- historical observation/search accounting;
- SQLite or any persistent ledger;
- sensitivity and signal-class schemas;
- candidate/detection records;
- crossing-window engine and beam models;
- full scheduler;
- service/alert daemon;
- irregular FOV, MOC, or ST-MOC;
- binary/orbital endpoint models;
- relic/failure-epoch trajectories;
- full iterative light-time and wave-optics models; and
- direct SPICE backend unless validation proves it necessary for v1 accuracy.

---

## 9. Release gates

V1 is blocked until all of these are true:

1. **Science gate:** `tusay2022_eq5_7_v1` reproduces the published equations, physical/catalog formulations agree on synthetic fixtures, the double-retarded Rx construction fails its negative test, and an astrometry-aware reviewer approves the event convention.
2. **Frame/time gate:** every coordinate product declares frame, origin, time scale, and corrections, with independent comparisons inside tolerance.
3. **Reproducibility gate:** a network-disabled clean run with pinned resources reproduces stable IDs and equivalent rows.
4. **Boundary gate:** `src/sglseti` has no observation ledger, historical-coverage state, candidate model, or archive-ingest implementation.
5. **Workflow gate:** the historical and commensal examples both run end to end.
6. **Quality gate:** supported-platform tests pass and warnings/errors are covered.
7. **Documentation gate:** users can tell which model was calculated and cannot reasonably mistake a target product for evidence of observational coverage.

---

## 10. Definition of done

Implementation is complete when:

- `generate_loci()` produces reproducible past/current/future locus and corridor records from the same request model;
- the CLI can process a historical epoch table and a future site/window request;
- outputs preserve epoch join keys, units, frames, catalog and physical-event epoch semantics, model identity, resource hashes, and validity flags;
- simple current/future visibility and circular-FOV grouping work without a ledger;
- required formats round-trip or validate;
- science and astrometry reviewers approve the v1 model/tolerance documentation;
- default execution and tests do not require network access; and
- all v1 PRD acceptance criteria pass.

At that point, an archive-cross-match or historical-coverage project can consume `sglseti` outputs without forcing persistence or archive-specific concerns back into this package.
