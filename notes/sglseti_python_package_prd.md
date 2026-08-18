---
title: "SGLSETI Python Package — Product Requirements Document"
date: 2026-08-17
status: "Draft PRD v0.1"
package_name: "sglseti"
license_recommendation: "BSD-3-Clause or MIT"
tags:
  - python
  - product-requirements
  - SETI
  - solar-gravitational-lens
  - astronomy-software
  - observation-coverage
---

# SGLSETI Python Package — Product Requirements Document

## 1. Document purpose

This document specifies an open-source Python package named **SGLSETI** for planning, recording, and evaluating searches for technosignatures associated with stellar-gravitational-lens communication infrastructure.

The package will:

- calculate Solar gravitational lens transmit and receive corridors for nearby stars;
- calculate possible beam-crossing windows for Earth, observatories, and spacecraft;
- export telescope-ready coordinates and sky regions;
- ingest observation and search-pipeline metadata;
- maintain a **small, local, version-controlled SQLite database** of observations, coverage, candidates, models, and provenance;
- generate quantitative coverage reports that preserve the multidimensional nature of a SETI search;
- operate reproducibly offline after catalogs, ephemerides, and kernels have been acquired.

The package is a scientific planning and metadata system. It is not initially a raw-voltage, image-reduction, or signal-detection pipeline.

---

## 2. Product summary

### 2.1 Product statement

> SGLSETI converts the stellar-gravitational-lens network hypothesis into reproducible sky regions, observing windows, searchable metadata, and cumulative coverage constraints.

### 2.2 Core workflow

```text
stellar catalog + covariance
              |
Solar-System ephemeris + observatory state
              |
       Rx/Tx light-time solver
              |
  SGL corridor and crossing windows
              |
 telescope planning and data exports
              |
 observation + pipeline metadata ingest
              |
 local committed SQLite coverage database
              |
 reports, plots, candidate follow-up, API
```

### 2.3 Primary differentiator

Most observing databases answer, “What data exist near this coordinate?” SGLSETI must answer:

> What portions of a moving, distance-dependent, model-dependent SGL technosignature hypothesis were observed, with what frequency, time resolution, signal-class sensitivity, and analysis pipeline?

---

## 3. Problem statement

SGL technosignature searches are difficult to accumulate scientifically because:

1. A hypothetical relay does not occupy one fixed sky coordinate.
2. Its apparent location depends on epoch, observatory, assumed heliocentric distance, receive/transmit role, stellar astrometry, and finite light time.
3. Different frequencies probe different physical components: a low-frequency radio observation may constrain local control traffic without constraining the lensed optical trunk.
4. A telescope observation is not equivalent to a completed search. The data must be processed by a pipeline capable of detecting a defined signal class.
5. Existing publications and archives use heterogeneous metadata.
6. “Target searched” summaries erase spectral, temporal, spatial, distance, drift-rate, and sensitivity coverage.
7. Reproducing a published coordinate years later requires the original astrometric catalog, ephemeris, time scale, and model version.

SGLSETI addresses these problems with a versioned scientific model, a standardized observation schema, and a committed local database.

---

## 4. Goals

### G1. Reproducible SGL geometry

Given a target, epoch, observatory, model, and relay-distance interval, independently reproduce the predicted Rx and Tx sky loci.

### G2. Explicit finite-light-time models

Distinguish incoming receive geometry from outgoing point-ahead transmit geometry.

### G3. Telescope-ready products

Export coordinates and regions in standard formats suitable for scheduling, visualization, and archive search.

### G4. Crossing calculations

Identify and rank times when Earth or another observer approaches a hypothesized communications axis.

### G5. Local committed observation database

Ship and maintain a compact SQLite database in the repository containing public observation, coverage, candidate, and provenance metadata.

### G6. Multidimensional coverage

Represent coverage across target, role, relay distance, sky, time, frequency, temporal resolution, drift/acceleration, polarization, signal class, and sensitivity.

### G7. Offline reproducibility

Support geometry and database queries without a network connection once required snapshots and kernels are installed.

### G8. Open scientific interchange

Support CSV, ECSV, JSON, YAML, VOTable, DS9 regions, and IVOA-inspired observation metadata.

### G9. Transparent uncertainty

Propagate catalog covariance and expose model uncertainty rather than publishing false precision.

### G10. Extensibility

Allow future models for off-axis relays, sub-minimum-distance lenses, compact stars, two-lens links, non-monopole caustics, and supporting infrastructure.

---

## 5. Non-goals for v1.0

SGLSETI v1.0 will not:

- perform full electromagnetic wave-optics simulation of a stellar lens;
- replace a telescope scheduler;
- process baseband radio voltages;
- perform optical pulse detection on raw images;
- classify all astronomical transients;
- claim that one link architecture is uniquely optimal;
- store raw telescope data in the committed SQLite database;
- provide autonomous messaging to candidate artifacts;
- model detailed stellar-corona magnetohydrodynamics;
- produce spacecraft navigation solutions for an actual SGL mission;
- infer extraterrestrial intent from a candidate.

Interfaces should permit future integrations with specialized tools.

---

## 6. Users and personas

### 6.1 SETI observer

Needs current sky coordinates, observing windows, sensitivity planning, and exports for a specific telescope.

### 6.2 Archive researcher

Needs to find existing datasets that intersect a historical SGL corridor or crossing window.

### 6.3 Signal-processing researcher

Needs machine-readable observation metadata and raw-data references, plus exact pipeline coverage parameters.

### 6.4 Astrometry researcher

Needs transparent coordinate frames, epochs, light-time equations, uncertainties, and ephemeris provenance.

### 6.5 Project coordinator

Needs target priorities, cumulative coverage reports, data gaps, candidate status, and follow-up plans.

### 6.6 Software contributor

Needs modular algorithms, deterministic tests, schema migrations, documented APIs, and small local fixtures.

### 6.7 Telescope operator

Needs concise target lists, angular rates, uncertainty regions, visibility windows, and observing constraints.

---

## 7. Principal use cases

### UC1. Calculate tonight's Proxima Rx and Tx corridors

A user supplies a site, time interval, and \(550\)–\(2500\) AU range. The package returns nominal and uncertainty regions in ICRS, AltAz visibility, angular rates, and DS9 files.

### UC2. Find Wolf 359 crossing windows

A user requests Earth-to-axis closest approaches over ten years. The package returns minima, impact parameters, relative velocities, and durations for assumed beam radii.

### UC3. Plan a radio mosaic

A user provides a radio primary-beam model. The package chooses pointings that cover a specified fraction of the Alpha Centauri Rx corridor.

### UC4. Search an optical archive

The package intersects historical image footprints and exposure times with an SGL corridor and reports which relay distances were covered.

### UC5. Record a published null result

A curator adds observation metadata, pipeline parameters, sensitivity curves, and a publication reference. The database computes coverage assertions without storing raw data.

### UC6. Generate a coverage report

A user asks which portions of the Proxima hypothesis have been constrained in 1–12 GHz, 380–950 nm, and thermal IR.

### UC7. Track a candidate

A moving source is linked to detections across epochs. The package fits parallax, compares the motion with an SGL hypothesis, records follow-up status, and preserves alternative identifications.

### UC8. Reproduce a paper's target coordinates

A user selects the historical catalog, ephemeris, model version, and epoch. The package generates a provenance bundle and compares its result with the published position.

### UC9. Commensal field check

An observatory submits its current or planned pointings. The package reports any intersections with SGL corridors or crossing hypotheses.

### UC10. Refresh catalogs

A maintainer downloads a new stellar-catalog snapshot, regenerates derived target rows, runs validation, and commits a migration plus a new database release.

---

## 8. Scientific model

### 8.1 Coordinate systems

Canonical internal conventions:

- stellar astrometry: **ICRS/BCRS-compatible** position and velocity;
- Solar-System dynamics: SPICE-compatible inertial frame, normally `J2000`/ICRF alignment;
- local relay coordinates: Solar-System barycentric Cartesian vectors;
- observing products: astrometric ICRS RA/Dec;
- optional apparent products: geocentric and topocentric apparent coordinates;
- telescope visibility: AltAz with refraction disabled by default and explicitly enabled by user choice.

The package must never silently mix:

- ICRS and apparent-of-date coordinates;
- UTC and TDB;
- barycentric and heliocentric origins;
- geometric and light-time-corrected directions.

Every returned coordinate object must expose frame, origin, epoch, and correction type.

### 8.2 Time systems

Canonical storage:

- observation start/end: MJD UTC;
- precision ephemeris calculations: TDB/ET seconds past J2000;
- user-facing timestamps: ISO-8601 UTC;
- optional local civil time: presentation only.

Leap-second and kernel provenance must be recorded. SPICE uses TDB-like ephemeris time for its state calculations; the package must rely on maintained conversion libraries rather than hand-written offsets.

### 8.3 Stellar state

Minimum target state:

\[
\left(
\alpha,\delta,\varpi,
\mu_{\alpha*},\mu_\delta,
v_r,
t_0,
C
\right),
\]

where \(C\) is the astrometric covariance matrix.

The package will support:

- standard six-parameter linear space motion;
- missing radial velocity with an explicit prior or uncertainty flag;
- catalog acceleration terms;
- user-supplied binary or orbital solutions;
- Monte Carlo propagation of covariance;
- multiple catalog solutions per target.

### 8.4 Solar focal distance

For a lens star of mass \(M_\star\) and effective opaque radius \(R_\star\),

\[
r_g=\frac{2GM_\star}{c^2},
\]

\[
z_{\min}=\frac{R_\star^2}{2r_g}
=\frac{R_\star^2c^2}{4GM_\star}.
\]

For the Sun, the package validation constant should reproduce approximately

\[
z_{\min}=547.8\ {\rm AU}
\]

with the chosen solar constants.

The default search range is configurable; a recommended baseline is \(550\)–\(2500\) AU.

### 8.5 First-order relay locus

For target direction \(\hat{\mathbf n}\), Solar position \(\mathbf r_\odot\), and range \(z\),

\[
\mathbf r_{\rm relay}
=
\mathbf r_\odot-z\hat{\mathbf n}.
\]

For observatory state \(\mathbf r_{\rm obs}\),

\[
\hat{\boldsymbol\ell}
=
\frac{\mathbf r_{\rm relay}-\mathbf r_{\rm obs}}
{\left|\mathbf r_{\rm relay}-\mathbf r_{\rm obs}\right|}.
\]

This is the package's `linear` model and should be clearly labeled as an approximation.

### 8.6 Receive light-time model

The `rx` model solves for photons emitted by the target in the past and arriving at a local relay.

Unknown epochs may include:

- target emission \(t_e\);
- solar-lens passage \(t_s\);
- relay reception \(t_r\);
- observatory detection of relay emission or reflection \(t_o\).

The implementation should permit several levels:

1. **Rx linear:** propagated apparent stellar direction at a selected epoch.
2. **Rx retarded:** fixed-point iteration for target-to-Sun light time.
3. **Rx full:** target-to-lens, lens-to-relay, relay-to-observer light times with moving bodies.

The default scientific product should use `rx_retarded` or higher.

### 8.7 Transmit point-ahead model

The `tx` model solves for a relay transmission that reaches the target in the future.

Unknown epochs may include:

- relay emission \(t_r\);
- solar-lens passage \(t_s\);
- target arrival \(t_a\);
- observatory detection \(t_o\) when imaging the relay.

The target state must be propagated to \(t_a\), not evaluated at the observation epoch.

A useful diagnostic scale is

\[
\Delta\theta_{\rm Tx-Rx}\sim\frac{2v_\perp}{c}.
\]

The package must return the calculated vector, not only this approximation.

### 8.8 Apparent corridor

For a relay-distance interval \([z_1,z_2]\), sample or adaptively trace the apparent locus. The output region should include:

- nominal polyline;
- width from astrometric covariance;
- optional width from stationkeeping prior;
- optional width from off-axis model;
- mapping from line position to \(z\);
- angular-rate vectors.

Adaptive sampling is required where parallax curvature or uncertainty changes rapidly.

### 8.9 Crossing model

For axis direction \(\hat{\mathbf n}(t)\) and observer heliocentric position \(\mathbf r(t)\),

\[
b_\perp(t)=
\left|
\mathbf r(t)
-
[\mathbf r(t)\cdot\hat{\mathbf n}(t)]\hat{\mathbf n}(t)
\right|.
\]

The crossing solver must:

- bracket local minima over a requested interval;
- refine each minimum numerically;
- record the sign of \(\mathbf r\cdot\hat{\mathbf n}\);
- propagate stellar-state uncertainty;
- calculate event durations for user-supplied beam models;
- allow Earth center, observatory, Moon, planet, or spacecraft as observer.

### 8.10 Beam models

Initial beam models:

- constant-radius cylinder;
- constant angular divergence cone;
- diffraction-limited direct beam;
- Gaussian beam;
- user-supplied radius-versus-distance;
- SGL heuristic core plus halo;
- scanned beam with duty cycle.

A beam model produces detectability geometry, not a claim about transmitter design.

### 8.11 Uncertainty model

Sources:

- stellar astrometric covariance;
- radial-velocity uncertainty;
- companion or acceleration uncertainty;
- Solar-System ephemeris uncertainty;
- observatory coordinates and timing;
- unknown relay range;
- stationkeeping prior;
- model-family uncertainty.

Outputs:

- nominal locus;
- percentile contours;
- sample cloud;
- covariance where locally meaningful;
- separate statistical and model uncertainty.

---

## 9. Functional requirements

### FR-001 — Target catalog

The package shall store and query target stars with aliases, catalog identifiers, astrometry, covariance, distance, radial velocity, multiplicity flags, and provenance.

### FR-002 — Catalog import

The package shall import a user-selected Gaia or custom catalog subset and retain the source query, release identifier, retrieval date, and checksums.

### FR-003 — Ephemeris backend

The package shall support a local SPICE backend. A JPL Horizons backend may be provided for validation and convenience.

### FR-004 — Observatory registry

The package shall store observatory codes, geodetic coordinates, altitude, timezone, horizon masks, and provenance.

### FR-005 — Rx corridor

The package shall compute receive-node loci for one or more relay distances and epochs.

### FR-006 — Tx corridor

The package shall compute transmit-node loci using future target positions and finite light time.

### FR-007 — Combined corridor

The package shall return Tx and Rx products together and quantify their angular and physical separation.

### FR-008 — Uncertainty propagation

The package shall generate Monte Carlo or linearized uncertainty regions from catalog covariance.

### FR-009 — Crossing search

The package shall locate closest approaches between selected observer trajectories and hypothesized link axes.

### FR-010 — Visibility

The package shall calculate AltAz, airmass, Sun/Moon separation, darkness, and tracking rates for selected sites.

### FR-011 — Sky-region export

The package shall export DS9 regions, CSV/ECSV, JSON, YAML, and VOTable products.

### FR-012 — Observation ingest

The package shall ingest observation manifests from YAML, JSON, CSV, or a Python API.

### FR-013 — Pipeline ingest

The package shall record search algorithms, software versions, parameters, signal classes, and execution provenance.

### FR-014 — Sensitivity metadata

The package shall store scalar thresholds and tabulated sensitivity curves as functions of frequency, pulse width, drift rate, sky position, or other supported axes.

### FR-015 — Coverage intersection

The package shall intersect observations and search runs with hypothesis regions to generate explicit coverage assertions.

### FR-016 — Coverage query

The package shall answer target-, role-, time-, distance-, frequency-, signal-class-, and sensitivity-constrained queries.

### FR-017 — Candidate tracking

The package shall store candidates, detections, alternative classifications, follow-ups, and status history.

### FR-018 — Provenance bundle

Every calculated region and coverage assertion shall be reproducible from stored model, code, catalog, kernel, and parameter identifiers.

### FR-019 — Committed database

The repository shall contain a released SQLite database with public metadata and a canonical deterministic SQL dump.

### FR-020 — Database validation

CI shall rebuild or migrate the database, run integrity checks, and compare the logical dump with the committed canonical dump.

### FR-021 — Offline mode

Core geometry and database operations shall work without network access when required local resources are installed.

### FR-022 — Archive references

The database shall store stable dataset identifiers, archive URIs, access conditions, and checksums without embedding raw observations.

### FR-023 — Report generation

The package shall generate Markdown, CSV, and JSON coverage reports.

### FR-024 — Plotting

The package shall plot corridors, uncertainty bands, crossing impact parameters, target visibility, and coverage summaries.

### FR-025 — Model registry

Scientific models shall be versioned, named, parameterized, and queryable.

### FR-026 — Reproducible random sampling

Monte Carlo calculations shall accept and record a random seed.

### FR-027 — Unit safety

Public APIs shall accept and return `astropy.units.Quantity` or explicitly documented units.

### FR-028 — Quality flags

Observations, search runs, and coverage assertions shall support quality flags and exclusion reasons.

### FR-029 — Publication linkage

Records shall support DOI, ADS bibcode, arXiv identifier, and free-text citation.

### FR-030 — Data release export

A release command shall produce the SQLite database, SQL dump, schema documentation, checksums, and a machine-readable manifest.

---

## 10. Nonfunctional requirements

### NFR-001 — Precision

Default calculations should be accurate to substantially better than a typical arcsecond-scale search region when input data permit. The package must not claim sub-arcsecond accuracy when stellar covariance or model uncertainty is larger.

### NFR-002 — Determinism

Given the same inputs, kernels, catalog snapshot, model version, and random seed, the package shall reproduce equivalent results.

### NFR-003 — Auditability

Every derived row shall include creation time, code version, model ID, and upstream provenance.

### NFR-004 — Performance

A single target corridor over one night and a few hundred distance samples should compute interactively on a laptop. A 1000-target annual batch should complete without distributed infrastructure.

### NFR-005 — Portability

Support current CPython on Linux, macOS, and Windows. Exact supported versions are set at implementation time.

### NFR-006 — Testability

Geometry functions should be pure where possible. External network calls must be mockable and excluded from default unit tests.

### NFR-007 — Small repository footprint

The committed database should contain metadata only and remain practical for ordinary Git. Large raw files and full survey products remain in external archives.

### NFR-008 — Backward-compatible data releases

Schema migrations shall be explicit. Released database versions shall remain readable or migratable.

### NFR-009 — Scientific transparency

Approximations shall be named and documented. The user shall be able to inspect intermediate vectors and epochs.

### NFR-010 — Safe defaults

The package shall not automatically transmit messages, control telescopes, or submit observing requests.

---

## 11. Package architecture

Recommended module layout:

```text
sglseti/
├── __init__.py
├── constants.py
├── models/
│   ├── base.py
│   ├── linear.py
│   ├── rx.py
│   ├── tx.py
│   ├── crossing.py
│   └── beams.py
├── catalogs/
│   ├── base.py
│   ├── gaia.py
│   ├── custom.py
│   └── covariance.py
├── ephemeris/
│   ├── base.py
│   ├── spice.py
│   ├── horizons.py
│   └── resources.py
├── coordinates/
│   ├── frames.py
│   ├── lighttime.py
│   ├── observer.py
│   └── uncertainty.py
├── observability/
│   ├── visibility.py
│   ├── tiling.py
│   └── schedules.py
├── coverage/
│   ├── intersect.py
│   ├── metrics.py
│   ├── reports.py
│   └── materialize.py
├── database/
│   ├── connection.py
│   ├── models.py
│   ├── migrations.py
│   ├── validation.py
│   └── release.py
├── ingest/
│   ├── observation.py
│   ├── pipeline.py
│   ├── publication.py
│   └── archive.py
├── export/
│   ├── ds9.py
│   ├── votable.py
│   ├── ecsv.py
│   └── json.py
├── plotting/
│   ├── sky.py
│   ├── crossings.py
│   └── coverage.py
├── cli/
│   ├── app.py
│   ├── zone.py
│   ├── crossing.py
│   ├── observe.py
│   ├── coverage.py
│   └── db.py
└── data/
    ├── sglseti.sqlite
    └── release_manifest.json
```

Repository-level resources:

```text
db/
├── schema.sql
├── migrations/
├── seed/
├── canonical_dump.sql
└── SCHEMA.md

data_sources/
├── catalogs.yml
├── ephemerides.yml
└── checksums.txt

examples/
├── observations/
├── notebooks/
└── target_lists/

tests/
├── unit/
├── integration/
├── regression/
└── data/
```

---

## 12. Recommended dependencies

Core:

- `numpy`
- `scipy`
- `astropy`
- `spiceypy`
- `pydantic`
- `typer`
- `rich`
- `sqlalchemy` or a thin typed wrapper over `sqlite3`
- `pyyaml`

Optional:

- `astroquery` for catalog and Horizons retrieval;
- `mocpy` for sky-footprint operations;
- `pandas` for import/export convenience;
- `matplotlib` for plotting;
- `healpy` for HEALPix coverage;
- `shapely` only for planar helper calculations, not primary spherical geometry;
- `jupyter` for notebooks;
- `pytest`, `hypothesis`, and coverage tools for development.

The package should minimize mandatory dependencies and isolate optional integrations.

---

## 13. Command-line interface

### 13.1 Target lookup

```bash
sglseti target show "Proxima Centauri"
sglseti target search --within-pc 10 --limit 50
```

### 13.2 Corridor calculation

```bash
sglseti zone \
  --target "Proxima Centauri" \
  --time "2027-03-15T04:00:00Z" \
  --site "GBT" \
  --z-min 550 \
  --z-max 2500 \
  --role both \
  --model full \
  --confidence 0.95 \
  --output proxima_2027
```

Expected products:

```text
proxima_2027.csv
proxima_2027.ecsv
proxima_2027.json
proxima_2027.reg
proxima_2027_provenance.yml
```

### 13.3 Crossing search

```bash
sglseti crossings \
  --target "Wolf 359" \
  --observer earth \
  --start 2027-01-01 \
  --stop 2037-01-01 \
  --direction outbound \
  --beam-radius 1000km,10000km,1au
```

### 13.4 Visibility

```bash
sglseti visibility \
  --region proxima_2027.json \
  --site "Keck" \
  --start "2027-03-15T00:00:00Z" \
  --stop  "2027-03-16T00:00:00Z"
```

### 13.5 Observation ingest

```bash
sglseti observe add observation.yml
sglseti observe validate observation.yml
sglseti observe list --target "Alpha Centauri"
```

### 13.6 Pipeline and search-run ingest

```bash
sglseti pipeline add pipeline.yml
sglseti search-run add run.yml
```

### 13.7 Coverage

```bash
sglseti coverage build --target "Proxima Centauri"
sglseti coverage report \
  --target "Proxima Centauri" \
  --role rx \
  --z 550:2500 \
  --freq 1GHz:12GHz \
  --signal-class narrowband \
  --format markdown
```

### 13.8 Database

```bash
sglseti db init
sglseti db migrate
sglseti db validate
sglseti db dump --canonical db/canonical_dump.sql
sglseti db release --version 0.1.0
```

### 13.9 Candidate tracking

```bash
sglseti candidate add candidate.yml
sglseti candidate fit-motion CAND-0001
sglseti candidate compare-sgl CAND-0001 --target "Barnard's Star"
```

---

## 14. Python API sketch

```python
from astropy.time import Time
from astropy import units as u
from sglseti import Target, Observer, SGLModel

target = Target.from_database("Proxima Centauri")
observer = Observer.from_site("GBT")
model = SGLModel.full()

result = model.corridor(
    target=target,
    observer=observer,
    time=Time("2027-03-15T04:00:00", scale="utc"),
    z_min=550 * u.au,
    z_max=2500 * u.au,
    roles=("rx", "tx"),
    confidence=0.95,
)

result.write("proxima.ecsv")
result.write_ds9("proxima.reg")
```

Crossing API:

```python
from sglseti.crossings import find_crossings
from sglseti.beams import ConstantRadiusBeam

events = find_crossings(
    target=target,
    observer="earth",
    start=Time("2027-01-01"),
    stop=Time("2037-01-01"),
    role="tx",
    beam=ConstantRadiusBeam(10_000 * u.km),
)
```

Coverage API:

```python
from sglseti.coverage import CoverageQuery

query = CoverageQuery(
    target="Proxima Centauri",
    roles={"rx"},
    z_range=(550 * u.au, 2500 * u.au),
    frequency_range=(1 * u.GHz, 12 * u.GHz),
    signal_classes={"narrowband"},
)

report = query.execute()
report.to_markdown("coverage.md")
```

---

## 15. Local committed database

### 15.1 Required design

The repository shall contain:

```text
sglseti/data/sglseti.sqlite
db/schema.sql
db/migrations/
db/seed/
db/canonical_dump.sql
sglseti/data/release_manifest.json
```

The SQLite database is committed to Git because:

- the project must work immediately offline;
- observation and coverage metadata are small;
- a versioned snapshot provides a stable citation target;
- users can query it without operating a server.

SQLite's binary format is not review-friendly. Therefore the project shall also commit:

- normalized seed CSV/YAML files for curated records;
- ordered schema migrations;
- a canonical text SQL dump;
- a release manifest with logical table checksums.

CI should compare the **logical database contents**, not require byte-identical SQLite pages.

### 15.2 Database scope

Store:

- target catalog subset and provenance;
- observatories;
- scientific models;
- computed hypothesis regions;
- crossing windows;
- observation metadata;
- search pipelines and runs;
- sensitivity metadata;
- coverage assertions;
- candidates and follow-up history;
- publication references;
- archive URIs and checksums.

Do not store:

- raw radio voltages;
- full astronomical images;
- large spectra;
- proprietary credentials;
- executable notebooks as blobs;
- unredacted private observatory notes.

### 15.3 Database release rules

1. All schema changes use migrations.
2. Seed records are reviewable text.
3. The released SQLite file contains no WAL or shared-memory sidecars.
4. Foreign-key checks must pass.
5. `PRAGMA integrity_check` must return `ok`.
6. The canonical dump uses stable ordering.
7. Every record includes source or provenance.
8. Derived records include model and code versions.
9. Release tags include database semantic version.
10. A DOI-capable archival release is recommended for major versions.

---

## 16. Database schema

### 16.1 Core entities

| Table | Purpose |
|---|---|
| `schema_version` | migration and release version |
| `catalog_source` | catalog identity, query, retrieval, checksum |
| `target` | canonical star/system identity and aliases |
| `target_astrometry` | epoch-specific astrometric solution and covariance |
| `target_physical` | mass, radius, luminosity, multiplicity, activity metadata |
| `observatory` | site coordinates and facility metadata |
| `ephemeris_source` | SPICE kernels, Horizons configuration, checksums |
| `model` | versioned geometry/beam/uncertainty model |
| `hypothesis_region` | computed Tx/Rx/local-infrastructure sky region |
| `hypothesis_sample` | optional sampled locus points with relay distance |
| `crossing_window` | closest-approach events and uncertainties |
| `observation` | top-level dataset or observing session |
| `observation_segment` | pointing/time/frequency segment |
| `signal_class` | controlled vocabulary of searched signatures |
| `pipeline` | software identity and supported signal classes |
| `search_run` | one execution of a pipeline on one dataset |
| `search_parameter` | normalized key/value parameter record |
| `sensitivity_curve` | sensitivity metadata and curve identity |
| `sensitivity_point` | tabulated sensitivity values |
| `coverage_assertion` | intersection of observation, search, and hypothesis |
| `coverage_cell` | optional materialized aggregate for fast reports |
| `candidate` | candidate identity and status |
| `candidate_detection` | individual candidate events |
| `candidate_hypothesis` | association with SGL or natural explanations |
| `publication` | DOI, ADS, arXiv, citation |
| `asset` | archive URI, checksum, access, format |
| `provenance` | code, environment, inputs, parent records |
| `quality_flag` | controlled data-quality vocabulary |
| `record_quality` | quality flags attached to records |

### 16.2 Canonical units

| Quantity | Canonical DB unit |
|---|---|
| RA, Dec | degrees, ICRS |
| angular size/rate | degrees; degrees/day |
| relay range | AU |
| Cartesian distance | km or AU, explicitly named |
| velocity | km/s |
| observation time | MJD UTC |
| ephemeris time | TDB seconds past J2000 |
| frequency | Hz |
| wavelength | metres when stored |
| bandwidth | Hz |
| exposure/sample time | seconds |
| flux density | Jy |
| integrated flux | W/m² |
| fluence | J/m² or photons/m², typed |
| EIRP | W |
| temperature | K |

Column names should carry units where ambiguity is possible.

### 16.3 Observation metadata and IVOA alignment

The observation schema should align where practical with IVOA ObsCore concepts:

- collection and dataset identifier;
- facility and instrument;
- spatial center and footprint;
- field of view and angular resolution;
- time start/end, exposure, and time resolution;
- spectral minimum/maximum and resolving power;
- calibration and data-product type;
- access URL and format.

SGLSETI adds fields not covered by generic ObsCore:

- target network hypothesis;
- Tx/Rx/crossing role;
- relay-distance interval;
- SGL model version;
- motion and point-ahead coverage;
- signal-class coverage;
- drift, acceleration, pulse width, and duty-cycle search;
- assumed transmitter distance and EIRP conversion.

### 16.4 Example observation table

```sql
CREATE TABLE observation (
    observation_id          TEXT PRIMARY KEY,
    obs_collection          TEXT NOT NULL,
    obs_publisher_did       TEXT,
    facility_name           TEXT NOT NULL,
    instrument_name         TEXT,
    program_title           TEXT,
    principal_investigator  TEXT,
    t_min_mjd_utc           REAL NOT NULL,
    t_max_mjd_utc           REAL NOT NULL,
    t_exptime_s             REAL,
    t_resolution_s          REAL,
    s_ra_deg_icrs           REAL,
    s_dec_deg_icrs          REAL,
    s_fov_deg               REAL,
    s_region_stcs           TEXT,
    moc_ascii               TEXT,
    em_min_m                REAL,
    em_max_m                REAL,
    em_res_power            REAL,
    polarization_products   TEXT,
    data_rights             TEXT,
    publication_id          TEXT,
    asset_id                TEXT,
    created_at_utc          TEXT NOT NULL,
    updated_at_utc          TEXT NOT NULL,
    provenance_id           TEXT NOT NULL,
    FOREIGN KEY(publication_id) REFERENCES publication(publication_id),
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id),
    FOREIGN KEY(provenance_id) REFERENCES provenance(provenance_id)
);
```

### 16.5 Example hypothesis region table

```sql
CREATE TABLE hypothesis_region (
    region_id               TEXT PRIMARY KEY,
    target_id               TEXT NOT NULL,
    role                    TEXT NOT NULL
                                CHECK(role IN (
                                    'rx', 'tx', 'both',
                                    'crossing', 'infrastructure',
                                    'outer_relay'
                                )),
    model_id                TEXT NOT NULL,
    observer_id             TEXT,
    t_min_mjd_utc           REAL NOT NULL,
    t_max_mjd_utc           REAL NOT NULL,
    z_min_au                REAL,
    z_max_au                REAL,
    confidence_level        REAL,
    nominal_path_json       TEXT NOT NULL,
    s_region_stcs           TEXT,
    moc_ascii               TEXT,
    angular_rate_json       TEXT,
    uncertainty_json        TEXT,
    created_at_utc          TEXT NOT NULL,
    provenance_id           TEXT NOT NULL,
    FOREIGN KEY(target_id) REFERENCES target(target_id),
    FOREIGN KEY(model_id) REFERENCES model(model_id),
    FOREIGN KEY(observer_id) REFERENCES observatory(observatory_id),
    FOREIGN KEY(provenance_id) REFERENCES provenance(provenance_id)
);
```

### 16.6 Example search run

```sql
CREATE TABLE search_run (
    search_run_id           TEXT PRIMARY KEY,
    observation_id          TEXT NOT NULL,
    pipeline_id             TEXT NOT NULL,
    run_started_utc         TEXT,
    run_finished_utc        TEXT,
    code_commit             TEXT,
    container_digest        TEXT,
    configuration_json      TEXT NOT NULL,
    result_status           TEXT NOT NULL
                                CHECK(result_status IN (
                                    'complete', 'partial',
                                    'failed', 'invalidated'
                                )),
    candidate_count         INTEGER NOT NULL DEFAULT 0,
    sensitivity_curve_id    TEXT,
    provenance_id           TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES observation(observation_id),
    FOREIGN KEY(pipeline_id) REFERENCES pipeline(pipeline_id),
    FOREIGN KEY(sensitivity_curve_id)
        REFERENCES sensitivity_curve(sensitivity_curve_id),
    FOREIGN KEY(provenance_id) REFERENCES provenance(provenance_id)
);
```

### 16.7 Example coverage assertion

```sql
CREATE TABLE coverage_assertion (
    coverage_id             TEXT PRIMARY KEY,
    region_id               TEXT NOT NULL,
    observation_id          TEXT NOT NULL,
    search_run_id           TEXT NOT NULL,
    signal_class_id         TEXT NOT NULL,
    z_min_au                REAL,
    z_max_au                REAL,
    freq_min_hz             REAL,
    freq_max_hz             REAL,
    time_overlap_s          REAL NOT NULL,
    spatial_fraction        REAL,
    distance_fraction       REAL,
    crossing_phase_min      REAL,
    crossing_phase_max      REAL,
    sensitivity_type        TEXT,
    sensitivity_value       REAL,
    sensitivity_unit        TEXT,
    assumptions_json        TEXT NOT NULL,
    quality                 TEXT NOT NULL,
    created_at_utc          TEXT NOT NULL,
    provenance_id           TEXT NOT NULL,
    FOREIGN KEY(region_id) REFERENCES hypothesis_region(region_id),
    FOREIGN KEY(observation_id) REFERENCES observation(observation_id),
    FOREIGN KEY(search_run_id) REFERENCES search_run(search_run_id),
    FOREIGN KEY(signal_class_id) REFERENCES signal_class(signal_class_id),
    FOREIGN KEY(provenance_id) REFERENCES provenance(provenance_id)
);
```

---

## 17. Observation manifest

Example YAML:

```yaml
observation_id: BL-GBT-ALPHACEN-SGL-001
collection: breakthrough-listen
facility: Green Bank Telescope
instrument: Breakthrough Listen backend

time:
  start_utc: "2021-11-06T03:14:00Z"
  end_utc: "2021-11-06T04:14:00Z"
  exposure_s: 3600
  resolution_s: 18.25
  timing_accuracy_s: 0.001

pointing:
  frame: icrs
  ra_deg: 0.0
  dec_deg: 0.0
  footprint:
    type: circle
    radius_deg: 0.1
  tracking: sidereal

spectrum:
  frequency_min_hz: 1.10e9
  frequency_max_hz: 1.90e9
  channel_width_hz: 2.79
  polarization_products: [XX, YY]

sgl_hypothesis:
  target: "Alpha Centauri"
  roles: [rx]
  z_min_au: 550
  z_max_au: 1000
  model: rx-retarded-v1
  region_file: alpha_cen_rx_2021.ecsv

data:
  archive_uri: "https://example.invalid/dataset"
  access: public
  checksum_sha256: "replace-with-real-checksum"

publication:
  arxiv: "2206.14807"

quality:
  flags: []
```

Pipeline manifest:

```yaml
pipeline_id: turbo-seti-narrowband
name: turboSETI narrowband drift search
version: "record-exact-version"
code_commit: "record-commit"

signal_classes:
  - narrowband_continuous

parameters:
  frequency_resolution_hz: 2.79
  integration_s: 18.25
  drift_min_hz_s: -4.0
  drift_max_hz_s: 4.0
  snr_threshold: 10
  de_doppler_reference: topocentric

sensitivity:
  type: flux_density
  curve_file: sensitivity.csv

provenance:
  container_digest: "sha256:..."
  environment_file: "environment.lock"
```

---

## 18. Coverage computation

### 18.1 Distinguish data coverage from search coverage

An observation can intersect an SGL region but provide no constraint if:

- the raw data were never searched;
- the time resolution is incompatible with the signal;
- the spectral resolution is too coarse;
- a candidate region falls in a flagged detector gap;
- the pipeline excludes the relevant drift rate;
- the sensitivity is unknown.

SGLSETI shall therefore create coverage only from the intersection of:

\[
\text{hypothesis region}
\cap
\text{observation support}
\cap
\text{search-run support}.
\]

### 18.2 Coverage axes

Minimum axes:

- target;
- model and role;
- relay distance;
- observation time;
- sky footprint;
- frequency;
- spectral resolution;
- time resolution;
- polarization;
- angular rate;
- Doppler drift;
- acceleration or jerk where relevant;
- pulse width;
- repetition period;
- signal class;
- sensitivity;
- duty-cycle assumptions.

### 18.3 Spatial-distance intersection

Because relay distance maps to position along the apparent corridor, the spatial intersection should return both:

- fraction of sky path covered;
- interval or weighted fraction of relay distance covered.

A wide telescope beam may cover all \(z\) values. A narrow optical field may cover only a small distance interval.

### 18.4 Frequency representation

Use frequency as the canonical spectral coordinate. Wavelength products are converted with vacuum \(c\). Coverage queries should support either frequency or wavelength input.

### 18.5 Sensitivity representation

Supported types:

- flux density;
- integrated flux;
- fluence;
- photon rate;
- line power;
- EIRP;
- isotropic-equivalent energy;
- transmitter optical power under an explicit link assumption;
- limiting magnitude;
- brightness temperature;
- thermal luminosity.

A sensitivity value without assumptions is invalid. EIRP conversions must state distance, antenna gain, integration, and duty cycle.

### 18.6 Materialized coverage cells

For fast dashboards, the package may build a `coverage_cell` table using configurable bins:

- logarithmic relay-distance bins;
- logarithmic frequency bins;
- time or crossing-phase bins;
- HEALPix/MOC spatial cells;
- signal-class categories;
- sensitivity quantiles.

The materialization is derived and rebuildable. The authoritative records remain observations, search runs, sensitivity curves, and coverage assertions.

### 18.7 Coverage reports

Required report forms:

- human-readable Markdown;
- machine-readable JSON;
- table CSV;
- frequency-versus-distance heat map;
- cumulative dwell time;
- sensitivity frontier;
- crossing-window timeline;
- signal-class matrix;
- list of unsearched high-priority cells.

---

## 19. Candidate model

### 19.1 Candidate status

Controlled states:

```text
new
instrumental_suspected
rfi_suspected
astronomical_suspected
solar_system_object_suspected
requires_followup
persistent_unexplained
rejected
confirmed_artificial_human
confirmed_natural
high_interest
```

No state should imply extraterrestrial origin without overwhelming evidence and external review.

### 19.2 Candidate detection

Each detection stores:

- time;
- observatory and dataset;
- sky localization and covariance;
- frequency or wavelength;
- bandwidth and duration;
- flux/fluence and uncertainty;
- polarization;
- drift/acceleration;
- image motion;
- signal morphology;
- raw-data reference;
- processing provenance.

### 19.3 SGL compatibility

The package computes:

- angular separation from predicted corridor;
- implied relay distance;
- motion-model residual;
- annual-parallax fit;
- anti-target-proper-motion fit;
- Tx versus Rx likelihood;
- coincidence with crossing window;
- alternative natural-object fits.

This output is a model-comparison aid, not a discovery claim.

---

## 20. Data sources and provenance

### 20.1 Stellar catalogs

Primary source:

- Gaia Archive or a curated Gaia-derived nearby-star subset.

Store:

- release/table name;
- exact ADQL or query;
- retrieval timestamp;
- row-level source identifiers;
- column definitions;
- checksum;
- transformations applied.

### 20.2 Solar-System ephemerides

Primary calculation backend:

- NASA NAIF SPICE kernels.

Validation and optional retrieval:

- JPL Horizons observer and vector ephemerides.

Store:

- kernel filenames;
- kernel versions or coverage dates;
- SHA-256 checksums;
- loaded-kernel order;
- frame and aberration settings;
- Horizons request parameters when used.

### 20.3 Observatory metadata

Sources may include:

- official observatory documentation;
- MPC observatory codes;
- IERS geodetic resources;
- user-supplied coordinates.

Never silently replace precise coordinates with a city center.

### 20.4 Publications

Store DOI, ADS bibcode, arXiv identifier, title, authors, year, and URL where available.

### 20.5 Software provenance

For each derived result:

- package version;
- Git commit;
- Python version;
- dependency lock or environment hash;
- model ID and parameters;
- random seed;
- input-record IDs;
- execution timestamp.

---

## 21. Algorithm requirements

### 21.1 Star propagation

1. Load catalog state and covariance.
2. Transform to a Cartesian phase-space representation.
3. Propagate to requested epoch using linear space motion or selected orbital model.
4. Transform to the required barycentric direction.
5. Retain uncertainty samples and provenance.

### 21.2 Rx solver

Pseudocode:

```text
input: target state, relay receive epoch, relay range, ephemeris
guess target emission epoch = receive epoch - catalog distance / c
repeat:
    propagate target to emission epoch
    compute Sun/lens state at passage epoch
    solve target -> lens -> relay path
    update emission and passage epochs
until convergence
compute relay barycentric position
solve relay -> observatory apparent direction
return epochs, vectors, coordinate, diagnostics
```

### 21.3 Tx solver

```text
input: target state, relay emission epoch, relay range, ephemeris
guess target arrival epoch = emission epoch + catalog distance / c
repeat:
    propagate target to arrival epoch
    compute Sun/lens passage epoch
    solve relay -> lens -> target path
    update passage and arrival epochs
until convergence
compute relay barycentric position
solve relay -> observatory apparent direction
return epochs, vectors, coordinate, point-ahead diagnostics
```

### 21.4 Convergence

The solver shall expose:

- iteration count;
- residual distance or angular error;
- convergence threshold;
- maximum iterations;
- failure reason.

No result should be returned as nominally valid after failed convergence.

### 21.5 Uncertainty sampling

Default:

- multivariate normal samples from catalog covariance;
- deterministic random seed;
- configurable sample count;
- optional quasi-random sampling;
- percentile region construction;
- convergence diagnostic on region width.

### 21.6 Crossing search

1. Coarsely sample the interval.
2. identify local minima in \(b_\perp(t)\);
3. bracket each minimum;
4. refine with scalar minimization;
5. sample astrometric uncertainty;
6. calculate beam-model durations;
7. merge duplicate minima;
8. return sorted events.

### 21.7 Corridor tiling

Given a telescope beam:

- sample corridor and uncertainty envelope;
- solve a set-cover or greedy tiling problem;
- support overlapping pointings;
- report spatial and relay-distance coverage;
- include angular-rate and tracking constraints.

---

## 22. Validation plan

### 22.1 Unit tests

- solar \(z_{\min}\);
- unit conversions;
- parallax scale;
- coordinate-frame round trips;
- time conversion;
- analytic linear-locus cases;
- constant-velocity point-ahead cases;
- crossing of a static axis by a circular orbit;
- database constraints and migrations.

### 22.2 SPICE/Horizons comparison

For selected dates and Solar-System bodies:

- compare observer state vectors;
- compare geocentric/topocentric apparent coordinates;
- verify aberration settings;
- record accepted numerical tolerances.

### 22.3 Published SGL examples

Regression fixtures should reproduce, within stated assumptions and uncertainties:

- published approximate Alpha Centauri SGL sky locations;
- published parallax behavior;
- the distinction between Rx and Tx for a high-proper-motion target;
- Wolf 359's favorable Earth-axis geometry.

The fixture must identify the historical catalog and ephemeris used. Disagreement may reflect improved astrometry rather than a software defect.

### 22.4 Database fixtures

Include small synthetic observations covering:

- full corridor;
- partial distance range;
- frequency overlap only;
- data with no search run;
- search with incompatible signal class;
- sensitivity curves;
- candidate detections.

### 22.5 Property-based tests

Examples:

- increasing relay distance decreases annual parallax;
- converting frequency to wavelength and back is stable;
- Rx and Tx converge for zero transverse motion;
- corridor samples remain on the anti-target side in the linear model;
- coverage cannot exceed one on normalized axes.

### 22.6 Scientific review

Before v1.0:

- independent astrometry review;
- independent SGL-geometry review;
- review by a radio SETI observer;
- review by an optical SETI observer;
- review of the database schema by an astronomical archive specialist.

---

## 23. Acceptance criteria for v1.0

### Geometry

- [ ] Compute Rx and Tx corridors for any catalog target with sufficient astrometry.
- [ ] Support \(z\)-range sampling and uncertainty regions.
- [ ] Return explicit finite-light-time epochs and convergence diagnostics.
- [ ] Export ICRS, apparent, and AltAz products with frame metadata.
- [ ] Reproduce solar \(z_{\min}\) near 547.8 AU.
- [ ] Identify distinct Tx and Rx axes for high-proper-motion stars.
- [ ] Find and rank crossing minima for Earth over user-selected intervals.

### Observation planning

- [ ] Generate DS9, ECSV, JSON, and VOTable region products.
- [ ] Calculate site visibility and angular tracking rates.
- [ ] Tile a corridor using a user-supplied field of view.

### Database

- [ ] Repository contains `sglseti.sqlite`.
- [ ] Repository contains schema, migrations, seeds, and canonical SQL dump.
- [ ] `PRAGMA integrity_check` passes.
- [ ] Foreign-key validation passes.
- [ ] Canonical dump is reproducible in CI.
- [ ] Published SGL searches can be represented without loss of essential metadata.
- [ ] Raw data are represented by stable references rather than embedded blobs.

### Coverage

- [ ] Ingest observation and pipeline manifests.
- [ ] Generate coverage assertions only when data and search-run support intersect.
- [ ] Query by target, role, distance, frequency, signal class, time, and sensitivity.
- [ ] Produce a Markdown coverage report and machine-readable equivalent.
- [ ] Distinguish “observed” from “searched.”

### Provenance

- [ ] Every derived region and coverage row has catalog, ephemeris, model, code, and parameter provenance.
- [ ] Release manifest includes database and resource checksums.
- [ ] Offline reproduction works from documented local resources.

### Documentation

- [ ] Installation and first-calculation tutorial.
- [ ] Coordinate/time conventions.
- [ ] Model assumptions and limitations.
- [ ] Database schema guide.
- [ ] Observation-curation guide.
- [ ] Contributor guide and code of conduct.

---

## 24. Roadmap

### v0.1 — Geometry prototype

- target schema;
- local SPICE integration;
- linear Rx corridor;
- ICRS and DS9 export;
- CLI skeleton;
- initial SQLite schema.

### v0.2 — Finite light time

- retarded Rx model;
- point-ahead Tx model;
- uncertainty propagation;
- observatory visibility;
- published-position regression tests.

### v0.3 — Crossing engine

- Earth and observatory crossing solver;
- beam models;
- event reports;
- Wolf 359 validation example.

### v0.4 — Observation database

- observation and search-run ingest;
- pipeline parameters;
- sensitivity curves;
- committed database release process;
- initial literature records.

### v0.5 — Coverage engine

- region intersections;
- relay-distance mapping;
- signal-class coverage;
- reports and plots;
- archival-query helpers.

### v0.6 — Candidate tracking

- detections;
- motion fitting;
- SGL compatibility;
- follow-up status;
- multi-observatory linkage.

### v0.8 — Public beta

- documentation;
- notebooks;
- stable CLI;
- data release;
- external scientific review.

### v1.0 — Reproducible research release

- validated models;
- stable database schema;
- curated historical coverage;
- offline resource bundle instructions;
- DOI release;
- published methods paper.

---

## 25. Risks and mitigations

### Risk: false precision

**Mitigation:** expose covariance, model families, and convergence diagnostics; avoid point-only outputs.

### Risk: binary database merge conflicts

**Mitigation:** commit reviewable seeds, migrations, and canonical dump; designate maintainers for database releases.

### Risk: catalog updates move predicted regions

**Mitigation:** version catalog snapshots and preserve historical models; never overwrite old derived products without provenance.

### Risk: coordinate-frame errors

**Mitigation:** strict typed frames, unit-aware APIs, SPICE/Astropy cross-checks, regression fixtures.

### Risk: coverage becomes an oversimplified score

**Mitigation:** preserve authoritative multidimensional records; treat aggregate scores as views only.

### Risk: heterogeneous sensitivity claims

**Mitigation:** typed sensitivity models with required assumptions and unit validation.

### Risk: raw archive links rot

**Mitigation:** store publisher dataset IDs, multiple URIs, checksums, and publication references.

### Risk: speculative models dominate development

**Mitigation:** keep a small validated baseline and implement advanced models as plugins.

### Risk: unreviewed candidate claims

**Mitigation:** conservative status vocabulary, alternative hypotheses, provenance, and independent confirmation requirements.

### Risk: external-service instability

**Mitigation:** cache catalog snapshots and kernels locally; make core workflows offline.

---

## 26. Open questions

1. What relay-distance prior should the default target planner use?
2. Should the committed database include precomputed regions or generate all regions on demand?
3. What spherical-region representation best balances portability and precision: STC-S, MOC, HEALPix cells, or multiple forms?
4. How should the package represent non-Gaussian astrometric uncertainty for binary systems?
5. Which two-lens and off-axis models are mature enough for the baseline registry?
6. How should optical pulse sensitivity be normalized across instruments with different dead time and coincidence logic?
7. What is the best common representation for radio drift/acceleration search coverage?
8. Should candidate data remain in the public committed database before publication?
9. Which observatory archives permit automated metadata ingestion?
10. What database size threshold should trigger a split between core and extended data releases?
11. Should the project host a central service, or remain a federated package plus versioned releases?
12. How should target priority scores expose subjective weights?
13. What standard should be used for crossing-window event identifiers?
14. How should the project represent a relay that is deliberately off the ideal focal line?
15. Can a future IVOA extension represent technosignature search-pipeline support directly?

---

## 27. Recommended governance

- open development repository;
- scientific steering group;
- database-curation maintainers;
- model-review process;
- semantic versioning for code and database;
- change proposals for schema and scientific models;
- signed releases and checksums;
- transparent issue tracker;
- clear candidate-communication policy;
- archival releases for citation.

A database contribution should require:

1. source citation;
2. observation manifest;
3. search-run manifest;
4. sensitivity assumptions;
5. validation;
6. reviewer approval.

---

## 28. Definition of success

SGLSETI succeeds when a researcher can make a precise statement such as:

> Using model `rx-retarded-v1`, Gaia catalog snapshot X, SPICE kernel set Y, and observatory Z, the observations in database release 1.0 cover 63% of the 550–2500 AU Proxima receive corridor between 1.1 and 1.9 GHz at the stated narrowband sensitivity, across three independent epochs, while leaving optical pulse, thermal IR, and most Tx-corridor parameter space unconstrained.

It also succeeds when another researcher can reproduce that statement offline from the release artifacts.

---

## 29. References and standards

### SGL and SETI literature

1. Michaël Gillon, “A novel SETI strategy targeting the solar focal regions of the most nearby stars,” arXiv:1309.7586.  
   <https://arxiv.org/abs/1309.7586>

2. Michael Hippke, “Interstellar communication network. III. Locating deep space nodes,” arXiv:2104.09564.  
   <https://arxiv.org/abs/2104.09564>

3. Stephen Kerby and Jason T. Wright, “Stellar Gravitational Lens Engineering for Interstellar Communication and Artifact SETI,” arXiv:2109.08657.  
   <https://arxiv.org/abs/2109.08657>

4. Nick Tusay et al., “A Search for Radio Technosignatures at the Solar Gravitational Lens Targeting Alpha Centauri,” arXiv:2206.14807.  
   <https://arxiv.org/abs/2206.14807>

5. Geoffrey W. Marcy, Nathaniel K. Tellis, and Edward H. Wishnow, “Laser Communication with Proxima and Alpha Centauri using the Solar Gravitational Lens,” arXiv:2110.10247.  
   <https://arxiv.org/abs/2110.10247>

6. Michaël Gillon, Artem Burdanov, and Jason T. Wright, “Search for an alien communication from the Solar System to a neighbor star,” arXiv:2111.05334.  
   <https://arxiv.org/abs/2111.05334>

7. Slava G. Turyshev, “Gravitational lensing for interstellar power transmission,” arXiv:2310.17578, v4.  
   <https://arxiv.org/abs/2310.17578>

### Official astrometry and ephemeris resources

8. JPL Solar System Dynamics, “Horizons System.”  
   <https://ssd.jpl.nasa.gov/horizons/>

9. NASA Navigation and Ancillary Information Facility, “SPICE.”  
   <https://naif.jpl.nasa.gov/naif/>

10. NASA NAIF, “SPK Required Reading.”  
    <https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/spk.html>

11. NASA NAIF, “Reference Frames.”  
    <https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/frames.html>

12. European Space Agency, “Gaia Archive.”  
    <https://gea.esac.esa.int/archive/>

### Observation metadata standards

13. International Virtual Observatory Alliance, “Observation Data Model Core Components and its Implementation in the Table Access Protocol, Version 1.1.”  
    <https://www.ivoa.net/Documents/ObsCore/>

14. International Virtual Observatory Alliance, “Simple Image Access Version 2.0.”  
    <https://www.ivoa.net/documents/SIA/20151223/REC-SIA-2.0-20151223.html>
