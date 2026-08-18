---
title: "sglseti — Survey-Driven Improvements"
date: 2026-08-18
status: "Proposed post-v1 roadmap"
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

### 2.5 Complete science gates

- add a frozen Wolf 359 crossing regression fixture, preserving the known
  disagreement with the published crossing epochs as an explicit expected
  result;
- validate representative apparent positions against an independent SPICE,
  Horizons, or equivalent construction where possible; and
- publish an accuracy budget by model, observer type, epoch span, and target
  state provider.

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
   changing existing linear/Earth behavior.
2. Introduce registry schema v2 and independent orbital fixtures.
3. Add observation intervals and the continuous/adaptive locus API.
4. Implement propagated uncertainty and uncertainty-aware crossings.
5. Add deterministic chunking, vectorization, and archive-scale benchmarks.
6. Implement higher-fidelity light-time and broader geometry models only after the baseline survey pipeline can measure its own completeness.
