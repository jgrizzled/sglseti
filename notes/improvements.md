---
title: "sglseti — Survey-Driven Improvements"
date: 2026-08-18
status: "In progress for v1.1 (items 6.1-6.5, 6.7-6.12 landed; 6.13 demand-driven)"
tags:
  - solar-gravitational-lens
  - astrometry
  - archive-survey
  - roadmap
---

# sglseti — Survey-Driven Improvements

## 1. Purpose

The first archive-facing consumer of `sglseti`, `sgl-seti-survey`, needs
more than nominal point coordinates to turn archival observations into
scientific constraints. This note records the package improvements exposed
by that use case.

The existing product boundary remains sound: `sglseti` owns versioned SGL
geometry, target and observer state propagation, uncertainty, generic target
regions, and reproducible exports. Archive discovery, observation ingest,
instrument footprints, signal searches, candidates, and coverage accounting
remain downstream responsibilities.

The priorities below distinguish improvements required before publishing
survey constraints from capabilities that can follow after the first
archive pipeline is operational.

## 2. Priority 0 — science and validation blockers

### 2.1 Pluggable target-state models

Replace the assumption that every endpoint can be represented by one linear
six-dimensional astrometric state with a versioned target-state-provider
interface. A provider must return the target direction or physical state at
the model-requested epoch and expose its epoch semantics, frame, origin,
validity interval, uncertainty model, and content identity.

Initial provider families:

- `linear_astrometry_v1`, preserving the current behavior;
- `acceleration_astrometry_v1` for catalog acceleration solutions;
- `two_body_orbit_v1` for resolved components and system barycenters;
- `sampled_state_v1` for externally generated, checksummed ephemerides; and
- a future planet or other moving-endpoint provider without overloading a
  stellar component model.

This is required for bright and multiple nearby systems such as Alpha
Centauri and Sirius, for which a generic Gaia five-parameter solution is
absent or scientifically inadequate. Tx role epochs can be years into the
future, so small unmodeled accelerations can become material.

Acceptance criteria:

- Existing linear-model fixtures remain numerically unchanged.
- Registry validation refuses to label an accelerating or orbital endpoint
  as linear while allowing it through an appropriate provider.
- At least one resolved-binary component and one system-barycenter fixture
  are verified against an independent ephemeris or published orbital
  solution.
- Every output row identifies the target-state provider and version.

**Status (v1.1, 2026-08-18):** the versioned `TargetStateProvider`
protocol is defined in `sglseti/providers.py` (epoch semantics, frame,
origin, validity interval, uncertainty model, solution-level warnings, and
content identity), with `linear_astrometry_v1` as the baseline family and
`resolve_target_state_provider()` as the selection seam. The geometry core
now consumes target states exclusively through the protocol; existing
linear fixtures are numerically unchanged and the model rejects providers
with foreign epoch semantics. With item 2 of §6,
`acceleration_astrometry_v1` and `two_body_orbit_v1` are implemented
(selected via registry schema v2), registry validation refuses
accelerating/orbital flags on a linear target while accepting them through
the appropriate family, existing linear fixtures remain unchanged, and the
resolved-binary-component and system-barycenter acceptance fixtures are
verified against the published Alpha Cen AB (Pourbaix & Boffin 2016) and
Sirius AB (Bond et al. 2017) solutions via an independent Thiele-Innes
reference implementation
(`tests/data/reference/two_body_orbit_reference.py`). With item 9 of §6,
`sampled_state_v1` is implemented for externally generated, CHECKSUMMED
cartesian ephemerides (mandatory content checksum, declared epoch
semantics the geometry model enforces, declared interpolation on the
shared table machinery, hard coverage errors, a wrong-file consistency
guard against the reference astrometry, and an explicit refusal of
parameter-based uncertainty sampling) — and it is the family that models
`planet` endpoints, closing the moving-endpoint gap. Identity stability against future field growth is provided by the
generic canonical rules (defaulted fields and paths never enter
identities; greenfield baseline, 2026-08-18). With item 10 of §6, every
output row identifies the target- and observer-state provider (ID,
version, content hash) — the final §2.1 acceptance criterion.

### 2.2 Registry schema v2: covariance and per-value provenance

Extend the target registry beyond one free-form source string. The schema
should support:

- immutable catalog or literature identifiers and release versions;
- per-value provenance for position, parallax or distance, proper motion,
  radial velocity, acceleration, and orbital elements;
- uncertainties with units and a declared parameter ordering;
- the complete covariance or correlation matrix where available;
- reference-frame, origin, epoch, and time-scale metadata;
- endpoint identity (`star`, `component`, `barycenter`, `planet`, or another
  explicitly modeled kind);
- quality indicators and model-selection rationale; and
- a canonical content hash covering the full adopted solution.

Provide a documented migration path from schema v1 and keep schema-v1
registries loadable for the linear model.

**Status (v1.1, 2026-08-18):** registry schema v2 is implemented
(`sglseti/targets.py`, documented in `docs/registry.md`, exercised by
`examples/targets_advanced.yaml`). It supports
immutable catalog/literature identifiers with release versions, per-value
provenance with uncertainties and mandatory units, full
covariance/correlation matrices with a declared parameter ordering and
units, explicit provider selection, `quality` and `model_rationale`
metadata, and the `planet` endpoint kind (recognized but rejected until a
provider family models it). (Greenfield revision, 2026-08-18: with no external
consumers, the v1 schema, its dual loader, and the lowest-schema
normalization were removed before first operational use — the registry
has a single schema and the original "keep v1 loadable" requirement is
retired as moot.) Still open: acceleration/orbital covariance is stored but not
yet consumed by uncertainty propagation (§2.3).

### 2.3 Propagated uncertainty products

Add role- and epoch-aware uncertainty propagation through the complete
target-generation calculation. Relay-distance sampling describes the locus
along a corridor; it does not replace cross-track uncertainty from
astrometry, orbital motion, or the model.

The first implementation may use Monte Carlo sampling, with a later analytic
or unscented-transform path for performance. Products should include:

- nominal samples;
- a declared confidence level;
- along-track and cross-track covariance where locally meaningful;
- percentile envelopes or samples suitable for constructing sky regions;
- uncertainty contributions or labels for target state, observer state,
  ephemeris, and geometry-model floors; and
- explicit treatment of non-Gaussian orbital or sampled-state uncertainty.

An assumed search pad must remain distinct from a propagated confidence
region. Invalid and degraded uncertainty solutions must be surfaced just as
nominal geometry failures are today.

**Status (v1.1, 2026-08-18):** implemented in `sglseti/uncertainty.py` as
seeded Monte Carlo. `target_uncertainty()` assembles the sampling
covariance from registry-v2 per-value uncertainties (units validated
exactly, Gaia tangent-plane convention) and covariance/correlation
matrices; `draw_target_samples()` draws fully validated perturbed targets
(domain-violating draws rejected and redrawn — the explicit non-Gaussian
treatment, with orbital elements propagating through Kepler's equation to
empirical percentiles). `propagate_locus_uncertainty()` returns the
nominal point, per-sample sky offsets for region construction, the
declared confidence level with its empirical confidence radius, sky
covariance, along/cross-track sigmas against the local corridor tangent,
explicit contribution labels (target state propagated; observer state,
ephemeris, and model floors declared `not_propagated`), and surfaced
degraded/invalid sample counts. Propagated products carry
`UncertaintyMethod.PROPAGATED`, structurally distinct from assumed pads.
Still open: analytic/unscented fast path, propagation of observer-state
and ephemeris contributions, and wiring these products into the batch
export pipeline (item 5).

### 2.4 Time-dependent observer-state providers

Generalize `Observer` from Earth center or a fixed terrestrial site to a
versioned provider of barycentric observer states at arbitrary epochs.

Initial provider families:

- Earth center and terrestrial site, preserving current behavior;
- Solar-System body from the pinned planetary ephemeris;
- SPICE-kernel spacecraft state;
- checksummed tabular spacecraft ephemeris; and
- a programmatic provider for testing and specialized integrations.

Every provider must declare frame, origin, time scale, coverage, interpolation
policy, and content checksum. Requests and calculation IDs must include the
provider identity rather than a local path.

This is negligible for WISE at its native resolution but important for L2,
Earth-trailing, and interplanetary observatories. A displacement of 0.01 AU
at 550 AU is about 3.7 arcsec, already material for narrow-field work.

**Status (v1.1, 2026-08-18):** the versioned `ObserverStateProvider`
protocol is defined in `sglseti/providers.py` (frame, origin, time scale,
coverage, interpolation policy, content identity), with `earth_center_v1`
and `terrestrial_site_v1` as the baseline families preserving current
behavior exactly, and `resolve_observer_state_provider()` as the selection
seam now used by `observer_barycentric_au()`. With item 8 of §6 all four
richer families are implemented: `solar_system_body_v1` (any body the
pinned planetary ephemeris serves), `spacecraft_table_v1` (checksummed
tabular ECSV ephemeris; declared cubic-Hermite interpolation with
velocities, linear without; coverage errors outside the tabulated span),
`spacecraft_spice_v1` (SPK kernel via optional `spiceypy`; geometric
`spkgeo` states in the SPICE J2000 frame with the ~17 mas ICRS frame bias
declared; SPK coverage windows enforced), and `programmatic_observer_v1`
(runtime-registered state function with a caller-declared content
identity). The `Observer` spec and request YAML select the family by
kind; calculation IDs and manifests carry the path-free content identity
(REQUIRED pinned file checksums; generic canonical rules) — verified
path-independent. Crossings compose through the provider
layer (spacecraft crossing smoke test in
`tests/unit/test_observer_families.py`).

### 2.5 Complete science gates

- add a frozen Wolf 359 crossing regression fixture, preserving the known
  disagreement with the published crossing epochs as an explicit expected
  result;
- validate representative apparent positions against an independent SPICE,
  Horizons, or equivalent construction where possible; and
- publish an accuracy budget by model, observer type, epoch span, and target
  state provider.

**Status (v1.1, 2026-08-18; first tranche — §6 item 7):** the Wolf 359
fixture is frozen
(`tests/data/reference/wolf359_crossing_reference.{py,yaml}`,
`tests/regression/test_wolf359_crossing_fixture.py`): an independent
no-sglseti oracle on the pinned DE440s excerpt kernel reproduces the
Gillon et al. 2022 geometry, and the +10.6 h / +17.0 h offsets from the
published crossing epochs are asserted as the EXPECTED result (at the
published epochs the Earth sits 1.78 / 2.70 R_sun off-axis, outside the
paper's own 1.1 R_sun annulus), with 2-arcsec publication consistency on
the TRAPPIST-South tx pointing. Horizons cross-validation is frozen
(`horizons_reference.{py,yaml}`, `test_horizons_validation.py`): the
pinned kernel matches DE441 vectors to sub-meter, the builtin analytic
ephemeris to ~119 km, and the light-time-retarded solar direction from
the geocenter and the Green Bank site matches Horizons astrometric
coordinates to 0.002 / 0.009 mas — with the ~9 mas residual of the
UNRETARDED geometric direction asserted as the measured scale of the
deliberately omitted light-time term. With item 12 of §6 the accuracy
budget is published (`docs/accuracy_budget.md`): declared model
approximations, measured resource floors, and epoch-span/provider
degradations with their scaling laws, by model, observer type, epoch
span, and target-state provider — with the cited numbers pinned by
`tests/regression/test_accuracy_budget.py` (notably: the builtin-vs-
kernel RELAY-POINTING floor is <= 0.02 mas despite ~119 km absolute
ephemeris differences, because the geometry depends on the Earth-Sun
relative vector; and the tx-epoch amplification law mu*2d/c is verified
to 1 percent). All three §2.5 gates are closed.

## 3. Priority 1 — archive-survey integration

### 3.1 Observation intervals and swept loci

Add first-class observation intervals rather than treating every archival
record as an instantaneous midpoint. Preserve point epochs for backward
compatibility, but support:

- observation start, midpoint, and stop;
- exposure or integration duration;
- optional subintegration cadence;
- target position and rate at representative times; and
- a conservative swept locus or envelope over the full interval.

Short WISE exposures can continue to use a midpoint. TESS sectors, stacks,
scan products, and long radio integrations require interval-aware geometry.

**Status (v1.1, 2026-08-18):** `ObservationInterval` is a first-class model
(start/midpoint/stop, duration, optional subintegration cadence,
pass-through metadata); `interval_states()` returns target position and
finite-difference rates at its representative or cadence times, and
`swept_locus()` produces the conservative swept envelope over the full
interval (see §3.2 status). Point epochs are unchanged and remain the
right choice for short exposures. With item 10 of §6, requests support a
first-class `intervals` time mode: each interval materializes into its
labeled sample times (`<interval_id>@start|mid|stop` or the declared
subintegration grid) and every product row carries `interval_id`,
`interval_phase`, and `interval_duration_s`.

### 3.2 Continuous and adaptive corridor evaluation

Expose a public evaluator for the continuous mapping

```text
(target, role, observation time, observer, z) -> direction
```

and an adaptive sampler that guarantees a caller-selected maximum angular
deviation between the returned polyline and the continuous locus. This lets
downstream consumers choose a tolerance tied to an instrument's pixel scale
or PSF rather than an arbitrary number of distance samples.

Useful generic outputs include:

- conservative discovery envelopes over time and relay distance;
- ordered polylines retaining the mapping back to `z`;
- interval-boundary coordinates;
- swept envelopes over an observation interval; and
- helpers to refine a caller-supplied geometric intersection into one or
  more covered `z` intervals.

The package should not learn archive-specific footprint schemas. Exact
intersection with detector polygons, WCS distortion, chip gaps, or masks
belongs in the survey consumer.

**Status (v1.1, 2026-08-18):** implemented in `sglseti/locus.py`.
`evaluate_locus()` is the public continuous mapping; `adaptive_locus()`
bisects in reciprocal distance until every accepted segment's 1/4-1/2-3/4
probes deviate by at most half the caller's tolerance, so the returned
polyline (ordered, z-mapped, with relay-range boundary coordinates and the
achieved deviation recorded) stays within the tolerance; budget exhaustion
attaches an explicit warning rather than weakening the bound silently.
`swept_locus()` applies the same midpoint-probe scheme in time over an
`ObservationInterval` and reports a conservative `envelope_pad_arcsec`;
`covered_z_intervals()` refines an opaque caller `contains(ra, dec)`
predicate into covered z intervals with verified-covered endpoints (no
archive footprint schema enters the package). Notable model fact: for the
antipode and tx roles the locus is exactly a great-circle arc (the catalog
direction is z-independent), so two points suffice; only rx curves.

### 3.3 Uncertainty-aware crossing products

Extend crossing calculations from nominal events to distributions or bounds
on closest approach. Preserve the primary product as impact parameter rather
than a binary crossing verdict.

Add:

- uncertainty on `b_min`, closest-approach time, and transverse speed;
- observation-interval minimization of `b(t)`;
- side-of-axis stability under the uncertainty model;
- results for time-dependent spacecraft observers; and
- an efficient point or interval API for joining a known schedule without a
  full multi-year scan.

Effective beam radii, annuli, scan patterns, wavelength-dependent response,
and transmitter duty cycle remain caller-supplied hypotheses.

**Status (v1.1, 2026-08-18):** `crossing_uncertainty()` re-minimizes the
impact parameter per sampled target inside a window around a nominal
event (a local refinement, never a new multi-year scan), yielding
empirical bounds and sigmas on `b_min`, closest-approach time, and
transverse speed, the full `b_min` sample list, and
`side_consistency_fraction` for side-of-axis stability; window-edge
minima degrade the product explicitly. `minimize_impact_parameter()`
minimizes `b(t)` over an `ObservationInterval` — with the existing
`impact_parameter()` point query, the efficient point/interval API for
joining a known schedule. With item 11 of §6, results for time-dependent
spacecraft observers are VERIFIED
(`tests/regression/test_spacecraft_crossings.py`, on the real Wolf 359
scenario with the pinned kernel): a displacement along the beam axis
leaves the crossing unchanged, a cross-axis displacement shifts it by
exactly its magnitude split between `b_min` and `v_perp * dt`, and the
uncertainty-aware crossing, interval-minimum, and point-query products
all compose with a tabular spacecraft observer.

### 3.4 Vectorized, chunked, and cache-aware execution

The current laptop-scale engine is adequate for small requests, but an
archive survey will evaluate thousands of exposure epochs and many
uncertainty samples. Add:

- vectorized ephemeris and target-state evaluation where supported;
- deterministic chunked or iterator APIs that do not materialize the full
  result;
- caches keyed by scientific identity for repeated target/role/epoch states;
- bounded-memory export; and
- benchmarks covering archive-sized epoch lists, spacecraft observers, and
  uncertainty propagation.

Parallel execution may remain a downstream orchestration concern as long as
chunks are deterministic and independently reproducible.

**Status (v1.1, 2026-08-18):** implemented; measurements in
`docs/benchmarks.md`, driver in `benchmarks/archive_scale.py`.

- Caches keyed by scientific identity: `resolve_target_state_provider()`
  memoizes providers by the target's stable content hash, each provider
  memoizes propagated states per TDB epoch, `AstropyEphemeris` memoizes
  scalar body positions, and the site observer memoizes its GCRS offset —
  all bounded LRUs, all pure (bit-identical to uncached runs), cleared by
  `clear_provider_cache()`. Batch throughput rose ~4.3x at the reference
  configuration and the whole test suite runs ~3x faster.
- Vectorized evaluation where supported: provider `states_at()` (one
  `apply_space_motion` for many epochs, elementwise bit-identical, ~85x)
  and observer `positions_au()`.
- Deterministic chunked iteration: `plan_calculation()` +
  `iter_locus_chunks()` yield one corridor per target/role/epoch in the
  documented product order, sliceable by chunk index with unchanged
  identities; `generate_loci()` is now built on the same path.
- Bounded-memory export: `write_samples_stream()` writes `samples.csv`
  row-by-row (byte-identical to the batch writer) and ECSV in bounded
  parts, consuming the chunk stream without materializing the result.

With item 11 of §6, the spacecraft-observer benchmark row is measured
(333 vs 368 samples/s at the reference small batch — table interpolation
is not a bottleneck). Still open: vectorizing the rx-role per-distance
catalog propagation inside the geometry model itself (the dominant batch
cost — the antipode/tx epochs are z-independent and fully cached, rx
epochs are not).

### 3.5 Product and provenance extensions

Extend manifests and rows to record:

- target-state-provider ID and content hash;
- observer-state-provider ID and content hash;
- uncertainty method, confidence level, and sample count;
- observation-interval semantics;
- adaptive-sampling tolerance and achieved bound;
- package version and source revision used for the run; and
- all accuracy-floor and validity warnings relevant to the product.

VOTable is a useful interoperability addition. Generic MOC or ST-MOC export
may be offered for conservative discovery envelopes, but exact archive
footprint intersection and coverage MOCs belong in `sgl-seti-survey`.

**Status (v1.1, 2026-08-18; result schema v3, crossings schema v2):**
sample rows and crossing events record the target- and observer-state
provider identity (ID, version, content hash); rows carry
observation-interval semantics (`interval_id`/`interval_phase`/
`interval_duration_s`) via the new `intervals` request time mode;
manifests add per-owner provider summaries, an `uncertainty` block
(method + assumed half-width), declared `time_semantics`, the package
version (in the library-versions block), and an optional caller-supplied
`source_revision` — run metadata, never science identity. Adaptive
tolerance and achieved bound were already first-class on the locus
records (item 3). `votable` joins the output formats (`samples.vot`,
`events.vot`, astropy's built-in writer, units preserved). MOC/ST-MOC
export is DEFERRED deliberately: it would add a heavy dependency for a
product the survey consumer owns (footprint/coverage MOCs are explicitly
downstream, §5) — revisit only if a concrete envelope-exchange need
appears.

## 4. Priority 2 — higher-fidelity and broader hypotheses

### 4.1 Iterative physical-state and light-time model

Implement a separately named model family that solves the light-time legs,
observer-relay distance, Solar motion, and physical target state
consistently. It must not silently replace the frozen Tusay approximation.
Use it to quantify where the v1 model ceases to meet an instrument-specific
accuracy requirement.

### 4.2 Wavelength-aware focal and propagation models

Allow an explicitly selected model to account for practical impact
parameter, solar-corona limits, wavelength-dependent propagation, and a
user-declared focal-distance prior. These outputs should remain physical
hypothesis parameters, not universal claims about detectability.

### 4.3 Endpoint-orbit and stationkeeping hypothesis families

Support optional models for:

- communication aimed at a planet or an orbital uncertainty envelope rather
  than the host star;
- nominal station-kept relays with transverse or radial residuals;
- relay swarms distributed around the nominal focal line; and
- inactive or failed relays following free trajectories.

These should be separately versioned geometry families so a broad search
cannot be confused with coverage of the baseline on-axis hypothesis.

## 5. Explicit non-goals

The following remain outside `sglseti` even when motivated by the survey:

- querying or downloading archive holdings;
- normalizing ObsCore, SIA, TAP, or archive-specific metadata;
- exact detector-footprint and valid-pixel intersection;
- observation, analysis-run, candidate, or coverage databases;
- source extraction, forced photometry, shift-and-stack, radio or optical
  signal detection, and candidate classification;
- injection/recovery and instrument-completeness measurement;
- target prioritization and archive-selection policy; and
- population-level inference from detections or null results.

Those operations consume `sglseti` products but require archive and
instrument knowledge that would weaken the package's stateless scientific
boundary.

## 6. Suggested implementation order

1. Define target-state and observer-state provider protocols without
   changing existing linear/Earth behavior. — **Done (v1.1, 2026-08-18):**
   `sglseti/providers.py`; see the status notes under §2.1 and §2.4.
2. Introduce registry schema v2 and independent orbital fixtures. —
   **Done (v1.1, 2026-08-18):** schema v2 with provider selection,
   per-value provenance, covariance, and identifiers (`docs/registry.md`);
   `acceleration_astrometry_v1` and `two_body_orbit_v1` families; Alpha
   Cen AB and Sirius AB fixtures verified against an independent
   Thiele-Innes construction of the published solutions. See the status
   notes under §2.1 and §2.2.
3. Add observation intervals and the continuous/adaptive locus API. —
   **Done (v1.1, 2026-08-18):** `ObservationInterval` model and
   `sglseti/locus.py` (`evaluate_locus`, `adaptive_locus`, `swept_locus`,
   `covered_z_intervals`, `interval_states`). See the status notes under
   §3.1 and §3.2.
4. Implement propagated uncertainty and uncertainty-aware crossings. —
   **Done (v1.1, 2026-08-18):** `sglseti/uncertainty.py` (seeded Monte
   Carlo locus and crossing propagation) and
   `minimize_impact_parameter()`. See the status notes under §2.3 and
   §3.3.
5. Add deterministic chunking, vectorization, and archive-scale
   benchmarks. — **Done (v1.1, 2026-08-18):** identity-keyed caching,
   `iter_locus_chunks()`/`plan_calculation()`, vectorized
   `states_at()`/`positions_au()`, `write_samples_stream()`, and
   `benchmarks/archive_scale.py`. See the status note under §3.4 and
   `docs/benchmarks.md`.
6. Implement higher-fidelity light-time and broader geometry models only after the baseline survey pipeline can measure its own completeness.

Continuation order for the remaining v1.1 work (added 2026-08-18 after
items 1-5 landed; ordered to bump the result schema exactly once and to
write the accuracy budget only after the observer types it must cover
exist):

7. Science gates, first tranche (§2.5, P0; independent of everything
   else): the frozen Wolf 359 crossing regression fixture preserving the
   known disagreement with the published crossing epochs, and frozen
   Horizons cross-validation fixtures for Earth-based positions (one-time
   online fetch; offline tests thereafter).
8. Observer-state provider families (§2.4), easiest first: programmatic
   test provider, Solar-System body from the pinned ephemeris,
   checksummed tabular spacecraft ephemeris (builds the shared
   interpolation + checksum machinery), SPICE-kernel spacecraft (optional
   dependency). Include request-schema observer selection and
   calculation-ID provider identity. — **Done (v1.1, 2026-08-18):** all
   four families, request-YAML selection, and path-free content identity
   in calculation IDs and manifests. See the status note under §2.4.
9. `sampled_state_v1` target-state family (§2.1), reusing the tabular
   interpolation/checksum machinery from item 8. — **Done (v1.1,
   2026-08-18):** shared `_CartesianEphemerisTable` core, mandatory
   checksums, declared epoch semantics, and planet endpoints. See the
   status note under §2.1 and `docs/registry.md`.

Greenfield simplification (2026-08-18, between items 9 and 10): with no
external consumers yet, the interim identity-compatibility machinery was
removed in favor of two permanent canonical rules — default-valued
dataclass fields and `path` fields never enter identities, with content
checksums REQUIRED on file-backed observer and sampled-state specs — and
the registry collapsed to its single schema. Canonical schema bumped to
v2; every hash moved exactly once, establishing the frozen baseline for
the archival search.
10. Product and provenance extensions as ONE result-schema-v3 release
    (§3.5, closing §2.1's row-identity acceptance criterion and §3.1's
    interval-aware rows): target- and observer-provider IDs and content
    hashes on rows and manifests, uncertainty method/confidence/sample
    count, observation-interval semantics, adaptive-sampling tolerance
    and achieved bound, VOTable output, optional MOC/ST-MOC envelopes. —
    **Done (v1.1, 2026-08-18):** result schema v3 + crossings schema v2;
    MOC/ST-MOC deliberately deferred (downstream product, §5). See the
    status note under §3.5.
11. Spacecraft follow-through (§3.3, §3.4): verify crossings with a
    spacecraft observer (the crossing code already routes observers
    through the provider layer) and add the spacecraft benchmark row. —
    **Done (v1.1, 2026-08-18):** physical-invariant regression tests on
    the Wolf 359 scenario and the measured benchmark row. See the status
    notes under §3.3 and §3.4.
12. Science gates, second tranche (§2.5): the accuracy budget by model,
    observer type, epoch span, and target-state provider — writable in
    full once items 8-11 exist. — **Done (v1.1, 2026-08-18):**
    `docs/accuracy_budget.md`, with its measured numbers pinned by
    `tests/regression/test_accuracy_budget.py`. See the status note under
    §2.5.
13. Demand-driven performance tail (§2.3, §3.4; only if survey workloads
    need it): rx-role vectorized propagation inside the geometry model
    and the analytic/unscented uncertainty path.
