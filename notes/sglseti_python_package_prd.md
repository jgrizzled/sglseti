---
title: "SGLSETI Python Package — Product Requirements Document"
date: 2026-08-17
status: "Draft PRD v0.3"
package_name: "sglseti"
license_recommendation: "BSD-3-Clause or MIT"
tags:
  - python
  - product-requirements
  - SETI
  - solar-gravitational-lens
  - astronomy-software
  - archival-search
  - commensal-search
---

# SGLSETI Python Package — Product Requirements Document

## 1. Purpose and v1 scope

This document specifies v1 of **SGLSETI**, an open-source Python package that generates reproducible sky targets for searches for Solar gravitational lens (SGL) technosignatures.

V1 supports two uses of the same calculation engine:

1. **Archival target generation:** calculate where an SGL relay hypothesis would have appeared at one or more historical epochs so another tool or researcher can cross-reference those positions with an archive.
2. **Commensal target generation:** calculate current or future positions, visibility, and simple telescope pointings so an observing system can search an SGL region alongside its primary program.

The package ends at the generation and export of target products. Archive discovery, observation ingest, search-result tracking, cumulative historical-coverage accounting, and candidate management belong in other projects.

Normative terms such as **MUST**, **SHOULD**, and **MAY** describe v1 requirements in decreasing order of priority.

### 1.1 Terminology

| Term | Meaning in this PRD |
|---|---|
| archival target | A predicted SGL sky position or corridor evaluated at a past epoch |
| commensal target | A predicted SGL sky position or corridor evaluated now or in the future for use alongside another observation |
| target system | The remote star or stellar system associated with the hypothesized link |
| local relay | Hypothetical equipment in the Solar System on or near the Sun's focal line |
| role | `rx`, `tx`, or the comparison-only `antipode` geometry |
| relay range | Assumed heliocentric distance of the local relay |
| locus sample | One predicted coordinate for a target, role, epoch, observer, relay range, and model |
| corridor | The ordered set or envelope of locus samples across a relay-range interval |
| historical coverage | A conclusion about which hypothesis space past observations and pipelines actually searched; explicitly outside v1 |

### 1.2 Product boundary

```text
curated target astrometry + requested epochs
                    |
observer/site + Solar-System ephemeris
                    |
versioned Rx/Tx geometry + relay-range sampling
                    |
coordinates + corridor + motion + visibility + provenance
                    |
          machine-readable target products
             /                         \
 archive cross-reference         commensal integration
   (external system)               (external system)
```

SGLSETI owns everything through the target products. It does not own either downstream system.

---

## 2. Product statement and principles

> SGLSETI turns a curated stellar-system hypothesis, an observer, and past or future epochs into reproducible, telescope-usable SGL target regions.

V1 follows these principles:

- **One epoch-neutral engine.** Past, present, and future calculations use the same API and scientific model. “Archival” and “commensal” are workflows, not separate geometry implementations.
- **Target-list driven.** Routine operation uses a small, explicit, versioned target registry. V1 does not crawl for every nearby star.
- **Regions, not magic coordinates.** A relay-distance interval maps to a sky corridor. Uncertainty and model padding must not be hidden behind excess decimal precision.
- **Reproducible by construction.** A product identifies the target solution, requested times, observer, ephemeris, model and parameters, software version, and input hashes.
- **Stateless core.** Calculation does not depend on an observation ledger or mutable service database.
- **Offline capable.** Once the target registry and selected ephemeris/IERS resources are local, generation must not require network access.
- **Library first.** The Python API is authoritative; the CLI is a thin batch interface over it.
- **Explicit approximations.** A fast baseline model may ship in v1, but it must be named, versioned, tested, and described as an approximation.

---

## 3. Users and jobs to be done

### 3.1 Archive researcher

Given exact historical exposure times and a known observing site, generate target rows or DS9 regions that can be joined to an external archive query.

### 3.2 Commensal-search integrator

Given a target registry and current or future time grid, generate machine-readable positions, angular rates, and validity metadata suitable for a telescope or survey pipeline.

### 3.3 SETI observer

Given a future observing window, site, instrument field of view, and constraints, generate a compact set of candidate pointings and their usable windows.

### 3.4 Astrometry or methods researcher

Inspect the coordinate frames, light-time approximation, propagated stellar state, ephemeris identity, intermediate epochs, and warnings behind every result.

### 3.5 Software contributor

Add a geometry or ephemeris implementation behind stable typed interfaces and compare it with versioned regression fixtures.

---

## 4. Goals

### G1. Calculate targets at arbitrary epochs

Generate nominal Rx, Tx, and comparison loci for historical, present, and future epochs covered by the input astrometry and ephemeris.

### G2. Support batch archival work

Accept exact timestamp lists and time grids, retain caller-supplied epoch identifiers, and emit joinable tabular products without querying archives.

### G3. Support commensal planning

Provide current/future coordinates, angular rates, basic observability, and simple circular-field grouping without attempting full telescope scheduling.

### G4. Preserve scientific meaning

Keep target role, relay distance, model, observer, time scale, coordinate frame, correction type, uncertainty treatment, and quality flags explicit.

### G5. Make results reproducible offline

Produce a provenance manifest sufficient to repeat a calculation with pinned local inputs.

### G6. Provide telescope-ready interchange

Export ECSV, CSV, JSON, and DS9 region products. ECSV and JSON are the loss-minimizing formats; CSV and DS9 are convenience views.

### G7. Establish an extensible geometry boundary

Allow later addition of higher-fidelity light-time, binary-system, off-axis, and alternative-lens models without changing the batch workflow or output identity rules.

---

## 5. Non-goals for v1

V1 will not:

- discover, query, scrape, or download astronomical archive holdings;
- ingest observation metadata, pipeline runs, sensitivity curves, null results, or publications;
- decide whether an observation “covered” or “completed” part of the SGL hypothesis;
- maintain an observation ledger, coverage database, committed SQLite database, or coverage dashboard;
- store or analyze raw telescope data;
- detect signals, classify candidates, fit candidate motion, or coordinate follow-up;
- run as a persistent alerting or network service;
- control a telescope or submit observing requests;
- construct a conflict-free exposure and slew schedule;
- implement a general crossing-window or beam-intersection engine;
- perform full electromagnetic wave-optics simulation;
- provide spacecraft navigation solutions;
- automatically build an all-nearby-stars catalog;
- silently use generic component astrometry as a binary-system barycenter;
- model relic trajectories after hypothetical equipment failure;
- claim that a generated target is physically occupied or that one link architecture is uniquely correct.

Downstream projects may consume SGLSETI outputs for archive matching, historical-coverage accounting, or live alerting.

---

## 6. Principal use cases

### UC1. Generate historical target coordinates for archive timestamps

A researcher supplies a frozen target registry, a file containing exposure IDs and UTC midpoints from 2012–2024, an observatory, roles, and a relay-distance range. SGLSETI returns locus samples keyed by the original exposure IDs plus a manifest. The researcher performs the archive-footprint match elsewhere.

### UC2. Reproduce a published pointing

A researcher selects the historical target solution, epoch, site, ephemeris resource, and geometry model used by a paper. SGLSETI emits the coordinate and intermediate diagnostics needed to explain agreement or disagreement with the publication.

### UC3. Generate targets for the next observing night

An observer supplies a target list, site, time window, basic Sun/Moon/altitude constraints, relay range, and circular field of view. SGLSETI returns visible target regions, candidate observing windows, and conservative pointings.

### UC4. Feed a commensal pipeline

An integrator calls the Python API for a UTC time grid and obtains deterministic records with ICRS coordinates, apparent coordinates when requested, angular rates, model identifiers, and quality flags. The external pipeline decides whether its current field overlaps those targets.

### UC5. Compare Rx and Tx hypotheses

A user generates both roles for a high-proper-motion target and sees distinct, model-labeled loci and point-ahead diagnostics.

### UC6. Run without a network connection

A user repeats a calculation using local target, ephemeris, and Earth-orientation files and obtains scientifically equivalent rows and identical calculation IDs.

---

## 7. Scientific model and conventions

### 7.1 Coordinate systems

Canonical conventions are:

- target astrometry: ICRS with an explicit reference epoch;
- internal stellar state: ICRS-compatible Cartesian position and velocity;
- Solar-System body states: the frame and origin declared by the selected ephemeris adapter;
- geometric search products: topocentric or geocentric ICRS direction, explicitly labeled;
- apparent products: CIRS or AltAz with observation time and observer location attached;
- visibility: AltAz with atmospheric refraction disabled by default.

The package MUST NOT silently mix ICRS with apparent-of-date coordinates, barycentric with heliocentric origins, or geometric with aberration-corrected directions.

### 7.2 Time systems

- User timestamps are ISO-8601 UTC or `astropy.time.Time` values with an explicit scale.
- Output tables contain UTC and a precision-computation time representation such as TDB Julian date.
- Target catalog reference epochs retain their declared time scale; Gaia astrometric reference epochs are interpreted in TCB.
- A role's catalog-direction epoch is explicitly identified as an SSB light-arrival epoch. Any inferred physical target emission or arrival epoch is a separate field.
- Naive datetimes are rejected by the Python API. The CLI MAY interpret timestamps without an offset as UTC only when that behavior is stated in help and the manifest.
- Leap-second and Earth-orientation resources are delegated to maintained astronomy libraries and recorded in provenance.
- No command may silently substitute the host computer's local timezone.

### 7.3 Target state

The minimum v1 astrometric state is:

\[
(\alpha,\delta,\varpi,\mu_{\alpha*},\mu_\delta,v_r,t_0,\mathrm{scale}_0),
\]

plus a source citation or immutable source identifier.

The registry MUST distinguish a star, component, system barycenter, or other modeled endpoint. A missing radial velocity, invalid parallax, stale epoch, or unresolved binary assumption produces an explicit validation error or quality flag; it must not be silently replaced with zero.

V1 uses linear space motion for the baseline implementation. Callers needing orbital or acceleration models must provide an implementation supported by the future model interface or accept a flagged unsupported target.

### 7.4 Solar focal range

For lens mass \(M_\star\) and opaque radius \(R_\star\),

\[
r_g=\frac{2GM_\star}{c^2},
\qquad
z_{\min}=\frac{R_\star^2}{2r_g}.
\]

The solar validation fixture should reproduce approximately \(547.8\,\mathrm{AU}\) using its declared constants. V1 does not force one search prior; every request supplies or explicitly accepts a configured relay-distance interval.

### 7.5 First-order relay locus

For Solar position \(\mathbf r_\odot(t)\), a model-selected target direction \(\hat{\mathbf n}\), and relay range \(z\), the baseline local relay position is

\[
\mathbf r_{\rm relay}=\mathbf r_\odot(t)-z\hat{\mathbf n}.
\]

For observer position \(\mathbf r_{\rm obs}(t)\), the geometric line of sight is

\[
\hat{\boldsymbol\ell}=
\frac{\mathbf r_{\rm relay}-\mathbf r_{\rm obs}}
{\left|\mathbf r_{\rm relay}-\mathbf r_{\rm obs}\right|}.
\]

This equation is shared by the role models; the role model defines which propagated target state supplies \(\hat{\mathbf n}\).

### 7.6 V1 role models

V1 MUST implement the reviewed model `tusay2022_eq5_7_v1` with public roles `antipode`, `rx`, and `tx`.

Let:

- \(t_o\) be the observer reception epoch requested by the caller;
- \(\rho\) be the relay–observer light-path length;
- \(z\) be the relay–Sun light-path length;
- \(d\) be the target–Sun light-path length; and
- \(\mathbf a(u)\) be the target's Gaia-like catalog direction indexed by SSB light-arrival epoch \(u\).

The corresponding physical target state is represented near \(u-d/c\). Under the published Tusay et al. approximation \(\rho\simeq z\), each role supplies the first-order relay equation with:

| Role | Catalog direction epoch \(u\) | Physical target state represented |
|---|---|---|
| `antipode` | \(t_o\) | state seen near \(t_o-d/c\) |
| `rx` | \(t_o-2z/c\) | emission near \(t_o-(2z+d)/c\) |
| `tx` | \(t_o+2d/c\) | arrival near \(t_o+d/c\) |

Before the \(\rho\simeq z\) approximation, the reconciled event bookkeeping is:

\[
u_{\rm rx}=t_o-(\rho+z)/c,
\qquad
t_{e,{\rm rx}}=u_{\rm rx}-d/c,
\]

\[
t_{a,{\rm tx}}=t_o+(z-\rho+d)/c,
\qquad
u_{\rm tx}=t_o+(z-\rho)/c+2d/c.
\]

The Rx \(d/c\) term belongs to the physical emission epoch and is already implicit in an arrival-indexed catalog direction. The implementation MUST NOT pass \(t_{e,{\rm rx}}\) to `SkyCoord.apply_space_motion()` as if it were a catalog epoch; that would double-retard the target.

Every sample MUST label the catalog epoch semantics, expose the approximate physical event epoch and kind, and record the \(\rho=z\), constant-\(d\), linear-motion, and neglected-Solar-motion assumptions. The complete derivation and prototype assessment are in [SGL Rx/Tx Light-Time Epoch Reconciliation](sgl_light_time_epoch_reconciliation.md).

A full iterative null-geodesic or multi-leg light-time solver is not a v1 requirement. The package MUST avoid generic labels such as `full` for an approximate implementation.

### 7.7 Relay-range sampling

A calculation over \([z_{\min},z_{\max}]\) produces an ordered corridor rather than only a midpoint.

V1 MUST support:

- caller-supplied relay ranges;
- explicit distance samples; and
- approximately uniform angular sampling using reciprocal distance \(q=1/z\).

For a one-AU baseline, \(q\) is approximately the parallax angle in radians. Reciprocal-distance sampling therefore maps more naturally to fixed angular fields than uniform-AU sampling.

Sampling identity is physical and deterministic: it depends on target, role, range, and sampling specification, not on the requested calendar date. Coordinates at those samples vary with epoch.

### 7.8 Observer and ephemeris

V1 supports Earth center and fixed terrestrial sites described by geodetic longitude, latitude, and height. Each result identifies which observer was used.

The default implementation MAY use Astropy's built-in Solar-System ephemeris for exploration. Reproducible scientific products SHOULD use a pinned local JPL ephemeris supported by Astropy and record its path-independent identity and checksum. A direct SPICE backend is deferred unless needed to satisfy v1 accuracy during validation.

Network retrieval is never implicit during a calculation. A separate, explicit resource-acquisition step may be added later.

### 7.9 Motion and observability

For current and future planning, v1 computes:

- finite-difference angular rates in \(d\mathrm{RA}\cos(\mathrm{Dec})/dt\) and \(d\mathrm{Dec}/dt\);
- altitude and azimuth for terrestrial sites;
- Sun altitude;
- Moon separation; and
- pass/fail results for simple altitude, darkness, and Moon-separation constraints.

These values assist planning but do not replace an observatory's pointing, refraction, or scheduling system.

### 7.10 Uncertainty and validity

V1 MUST separate:

- nominal astrometric/model output;
- a user-configured model or corridor half-width; and
- any statistically propagated uncertainty supported by the selected model.

A fixed half-width must be labeled `assumed`, not presented as catalog covariance. If full covariance propagation is not ready for v1, outputs must retain available covariance metadata, set `uncertainty_method=not_propagated`, and carry a warning. Coordinates remain useful for broad archival or commensal preselection, but documentation must state that narrow-field scientific use requires an independently justified envelope.

Every result has a validity status such as `valid`, `degraded`, or `invalid`, plus machine-readable reason codes. Failed model convergence or an out-of-coverage ephemeris never returns an apparently valid nominal row.

---

## 8. Input contracts

### 8.1 Curated target registry

The canonical v1 registry is a reviewable YAML file. A minimal example is:

```yaml
schema_version: 1
targets:
  barnard:
    display_name: "Barnard's Star"
    endpoint_kind: star
    priority: 1.0
    tags: [tier1, high-proper-motion]
    astrometry:
      frame: icrs
      ra_deg: 269.45207695861876
      dec_deg: 4.693364966576667
      parallax_mas: 546.9759
      pm_ra_cosdec_mas_per_yr: -801.551
      pm_dec_mas_per_yr: 10362.394
      radial_velocity_km_s: -110.11
      reference_epoch_jyear: 2000.0
      reference_epoch_scale: tcb
      source: "immutable catalog snapshot or citation"
```

The package MAY include a helper that resolves one explicitly named SIMBAD object into an unvetted draft block. Routine calculations must not resolve names over the network.

### 8.2 Calculation request

A calculation request contains:

- one or more target IDs;
- one or more roles;
- exactly one time mode;
- observer/site definition;
- relay-range and sampling definition;
- geometry-model ID and parameters;
- ephemeris and Earth-orientation resource settings;
- requested coordinate products;
- optional observability and circular-FOV settings; and
- requested output formats.

Supported time modes are:

1. one explicit epoch;
2. a caller-supplied list with stable `epoch_id` values; or
3. start, stop, and cadence.

### 8.3 Batch epoch table

The lossless input form is ECSV. CSV is accepted with documented units and UTC rules.

Required columns:

| Column | Meaning |
|---|---|
| `epoch_id` | caller-controlled stable join key |
| `time_utc` | ISO-8601 timestamp with UTC designator or offset |

Additional columns are passed through under a namespaced metadata field where practical. Passing an archive dataset ID through the calculation does not make SGLSETI an archive or observation database.

---

## 9. Output contracts

### 9.1 Locus-sample table

Each row MUST contain or reference:

| Group | Required fields |
|---|---|
| identity | calculation ID, epoch ID, target ID, role, relay-sample ID |
| time | observation UTC/TDB; catalog direction epoch with SSB-arrival semantics; approximate relay, Solar-lens, and physical target event epochs; target-event kind |
| range | relay distance in AU and reciprocal-distance value |
| geometry | geometric ICRS RA/Dec and observer origin |
| optional coordinates | apparent CIRS and AltAz, when requested and available |
| motion | RA-cos-Dec and Dec rates with units, when requested |
| model | model ID, model version, serialized parameters |
| provenance | target-source ID, ephemeris ID, resource hashes, package version |
| quality | validity status, warning/reason codes, uncertainty method |

Column names carry units when CSV cannot preserve unit metadata.

### 9.2 Corridor product

A corridor product contains:

- the ordered locus samples;
- a mapping from polyline position to relay range;
- nominal endpoints and midpoint;
- configured or propagated width with its method;
- maximum angular motion padding used for an exposure, if any; and
- a deterministic corridor ID.

### 9.3 Pointing product

When circular-FOV grouping is requested, each pointing contains:

- target and role;
- included relay-sample or segment IDs;
- conservative ICRS center and radius;
- instrument usable radius;
- proposed or representative time;
- valid observability window on the sampled grid;
- apparent coordinates, AltAz, Sun altitude, Moon separation, and rates; and
- the same model/provenance references as the underlying corridor.

V1 pointings are candidate zones, not a scheduled sequence.

### 9.4 Provenance manifest

Every command that writes science products also writes a JSON manifest containing:

- normalized calculation request;
- input file SHA-256 hashes;
- target-record hashes;
- geometry-model ID and version;
- ephemeris identity, coverage metadata, and checksum when file-backed;
- Earth-orientation resource identity when relevant;
- package, Python, Astropy, NumPy, and ERFA versions;
- coordinate/time conventions;
- warning summary;
- deterministic science-input hash; and
- non-deterministic generation timestamp kept separate from the science identity.

Absolute local paths and host-specific details should not be part of deterministic IDs.

### 9.5 Formats

V1 MUST support:

- ECSV locus/corridor tables;
- JSON locus/corridor data and manifest;
- CSV convenience tables; and
- DS9 region files.

VOTable is a SHOULD requirement and may slip if it would delay the tested core. FITS, MOC, and ST-MOC are post-v1 extensions.

---

## 10. Functional requirements

| ID | Requirement |
|---|---|
| FR-001 | Load and strictly validate a versioned local target registry. |
| FR-002 | Preserve target endpoint identity and astrometric provenance. |
| FR-003 | Accept single, listed, and regularly sampled historical/current/future epochs. |
| FR-004 | Retain stable caller-supplied epoch IDs through every output. |
| FR-005 | Propagate baseline target states with linear space motion. |
| FR-006 | Compute versioned `antipode`, `rx`, and `tx` local-relay loci. |
| FR-007 | Compute loci for explicit samples and reciprocal-distance intervals. |
| FR-008 | Support Earth-center and fixed terrestrial observers. |
| FR-009 | Produce geometric ICRS and requested apparent/topocentric coordinates without frame ambiguity. |
| FR-010 | Compute angular rates and basic observability for terrestrial sites. |
| FR-011 | Group adjacent relay-range segments into conservative circular-FOV pointings. |
| FR-012 | Generate ECSV, JSON, CSV, and DS9 products from the same typed result objects. |
| FR-013 | Generate deterministic calculation, corridor, sample, and pointing identities from science inputs. |
| FR-014 | Emit a provenance manifest and machine-readable warnings with every file-producing calculation. |
| FR-015 | Run without network access when inputs and resources are already local. |
| FR-016 | Expose the same capabilities through a public Python API and a thin CLI. |
| FR-017 | Fail clearly on unknown target IDs, invalid roles/ranges/times, unsupported target models, and unavailable ephemeris dates. |
| FR-018 | Avoid all dependencies on an observation ledger or historical-coverage state. |

---

## 11. Nonfunctional requirements

### NFR-001 — Scientific transparency

Public result objects expose intermediate role epochs, vectors or sufficient diagnostics, frames, origins, correction types, and approximation names.

### NFR-002 — Determinism

Equivalent normalized science inputs and resource versions produce the same stable IDs and numerically equivalent rows. Output ordering is stable.

### NFR-003 — Precision

V1 publishes validated tolerances for each model and coordinate product. It must not claim sub-arcsecond fitness when target, model, ephemeris, or Earth-orientation uncertainty is larger.

### NFR-004 — Performance

On a typical laptop, a calculation with 50 targets, two roles, 100 epochs, and 25 relay samples should complete without distributed infrastructure. A one-target, one-night calculation should feel interactive.

### NFR-005 — Portability

Support maintained CPython versions on Linux, macOS, and Windows. Exact versions are fixed in `pyproject.toml` and CI.

### NFR-006 — Testability

Geometry and sampling functions are pure where practical. Network access is absent from default tests. External-resource adapters are replaceable with deterministic fixtures.

### NFR-007 — Dependency restraint

The core dependency set should remain close to NumPy, Astropy, and a YAML parser. Optional integrations must not burden the basic target-generation workflow.

### NFR-008 — Safe defaults

No implicit downloads, telescope actions, archive mutations, or outbound requests occur during target calculation.

---

## 12. Public interfaces

### 12.1 CLI sketch

Validate local inputs:

```bash
sglseti validate targets examples/targets.yaml
sglseti validate request examples/historical.yaml
```

Generate historical target products:

```bash
sglseti generate \
  --targets examples/targets.yaml \
  --request examples/historical.yaml \
  --epochs archive_epochs.ecsv \
  --output-dir build/archive-targets
```

Generate a current/future commensal plan:

```bash
sglseti plan \
  --targets examples/targets.yaml \
  --request examples/commensal-night.yaml \
  --output-dir build/commensal-night
```

Inspect relay-range sampling without astronomy calculations:

```bash
sglseti samples --request examples/commensal-night.yaml
```

The CLI does not have `coverage`, `ingest`, `report`, `candidate`, or database commands.

### 12.2 Python API sketch

```python
from astropy import units as u
from astropy.time import Time
from sglseti import Observer, RelayRange, TargetRegistry
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.generate import generate_loci

registry = TargetRegistry.from_yaml("examples/targets.yaml")
observer = Observer.from_geodetic(
    name="example-site",
    longitude=-111.6003 * u.deg,
    latitude=31.9583 * u.deg,
    height=2096 * u.m,
)

result = generate_loci(
    targets=[registry["barnard"]],
    epochs=Time(["2021-11-06T03:14:00", "2027-03-15T04:00:00"], scale="utc"),
    epoch_ids=["archive-exposure-1", "future-slot-1"],
    observer=observer,
    relay_range=RelayRange(550 * u.au, 2500 * u.au),
    roles=("rx", "tx"),
    model=Tusay2022Eq57V1(),
)

result.write_ecsv("loci.ecsv")
result.write_json("loci.json")
```

The production API may refine names, but it must preserve typed time, units, stable IDs, and stateless operation.

---

## 13. Package architecture

A deliberately shallow v1 layout is preferred:

```text
pyproject.toml
src/sglseti/
├── __init__.py
├── models.py          # typed immutable inputs and result records
├── config.py          # YAML/ECSV parsing and validation
├── targets.py         # curated target registry and propagation inputs
├── ephemeris.py       # Astropy adapter and resource identity
├── geometry.py        # model protocol and baseline role models
├── sampling.py        # reciprocal-distance samples/segments
├── generate.py        # epoch-neutral batch calculation orchestration
├── observability.py   # site context and simple constraints
├── planning.py        # conservative circular-FOV grouping
├── provenance.py      # canonical serialization and hashes
├── export.py          # ECSV/JSON/CSV/DS9 writers
└── cli.py             # argparse-based command surface
tests/
├── unit/
├── integration/
├── regression/
└── data/
examples/
├── targets.yaml
├── historical.yaml
├── historical_epochs.ecsv
└── commensal-night.yaml
```

Modules may be split when they become difficult to navigate; v1 should not pre-create unused plugin, database, ingest, or service layers.

### 13.1 Recommended dependencies

Core:

- `numpy`;
- `astropy`;
- `PyYAML`;
- Python standard-library `dataclasses`, `argparse`, `hashlib`, `json`, and `pathlib`.

Optional:

- `astroquery` for an explicit, one-object SIMBAD import helper;
- `jplephem` when required by the chosen local JPL ephemeris path;
- `pytest` and `hypothesis` for development.

Direct `spiceypy`, `scipy`, `pydantic`, `typer`, database libraries, `mocpy`, `healpy`, and plotting packages are not v1 core requirements.

---

## 14. Validation plan

### 14.1 Unit tests

- target-schema validation, including missing radial velocity and invalid parallax;
- time parsing and rejection of ambiguous datetimes;
- unit conversions and frame metadata;
- solar minimum focal distance;
- reciprocal-distance partition completeness and deterministic IDs;
- analytic first-order relay geometry;
- zero-transverse-motion behavior;
- stable canonical serialization and hashing;
- output ordering and format round trips;
- observability constraint boundaries.

### 14.2 Geometry regression tests

Fixtures must cover at least:

- one historical Alpha Centauri or published-search epoch;
- a high-proper-motion target such as Barnard's Star;
- direct reproduction of Tusay et al. equations 5–7;
- equivalent physical-event and arrival-indexed catalog formulations for a synthetic moving target;
- rejection of the double-retarded Rx construction;
- distinct Rx and Tx results under `tusay2022_eq5_7_v1`;
- Earth-center versus topocentric parallax;
- multiple relay distances across 550–2500 AU;
- a present/future commensal night; and
- out-of-coverage or degraded ephemeris behavior.

Expected values include a documented source, model version, and tolerance. A test must not freeze unexplained output from the prototype as scientific truth.

### 14.3 Independent comparisons

Before v1:

- review the implementation against the independent derivation in [SGL Rx/Tx Light-Time Epoch Reconciliation](sgl_light_time_epoch_reconciliation.md);
- compare Solar-System state vectors against a pinned reference ephemeris;
- compare selected apparent coordinates with an independent Astropy or Horizons calculation;
- reproduce at least one published approximate SGL pointing within the assumptions and stated uncertainty; and
- have an astrometry-aware reviewer inspect frame, time, and observer conventions.

### 14.4 End-to-end tests

- historical ECSV in → locus ECSV/JSON/DS9 + manifest out;
- future request in → visible pointings + manifest out;
- identical run from a different working directory → identical science IDs;
- offline run with pinned resources → no network attempt;
- output from one run can be joined back to every input `epoch_id` without loss.

---

## 15. V1 acceptance criteria

### Historical target generation

- [ ] A user can calculate all requested target/role/range combinations for an arbitrary list of valid past UTC epochs.
- [ ] Every output row retains its input `epoch_id` and is suitable for an external positional cross-match.
- [ ] The same engine and model handle past and future epochs.
- [ ] No archive account, archive API, observation database, or ledger is required.

### Geometry

- [ ] `antipode`, `rx`, and `tx` implement the reviewed `tusay2022_eq5_7_v1` definitions.
- [ ] Every row distinguishes its catalog-direction epoch from its approximate physical target-event epoch.
- [ ] Rx regression tests reproduce \(u_{\rm rx}=t_o-2z/c\) and detect an erroneous additional \(-d/c\).
- [ ] A high-proper-motion fixture yields the expected Rx/Tx distinction.
- [ ] A relay-distance interval produces an ordered, distance-addressable corridor.
- [ ] Geocentric/topocentric origin, coordinate frame, time scale, and correction type are explicit.
- [ ] Invalid or degraded calculations carry machine-readable status and never masquerade as valid precision.

### Commensal target generation

- [ ] A user can calculate current/future targets on a time grid.
- [ ] A terrestrial-site calculation can return AltAz, Sun altitude, Moon separation, and angular rates.
- [ ] Simple constraints produce candidate windows.
- [ ] Adjacent reciprocal-distance segments can be grouped into conservative circular-FOV pointings.
- [ ] Pointings are clearly labeled as unscheduled candidate zones.

### Outputs and reproducibility

- [ ] ECSV, JSON, CSV, and DS9 are generated from one result model.
- [ ] Every product has a JSON provenance manifest.
- [ ] File-backed scientific resources are identified by checksum.
- [ ] Stable IDs exclude output path and generation timestamp.
- [ ] A documented offline rerun produces identical science IDs and equivalent numeric output.

### Quality and documentation

- [ ] Default unit, integration, and regression tests pass on supported Python versions.
- [ ] The quick start includes one historical and one commensal example.
- [ ] Scientific assumptions and prototype-derived code are documented.
- [ ] The package contains no coverage, observation-ingest, candidate, or database subsystem.

---

## 16. Risks and mitigations

### Risk: catalog arrival epochs and physical target-event epochs are mixed

**Mitigation:** use distinct typed fields and explicit epoch semantics; version the approximation as `tusay2022_eq5_7_v1`; test equivalent catalog and physical-state formulations; and include a regression test that detects double retardation.

### Risk: historical dates create false confidence from linear stellar motion

**Mitigation:** identify endpoint kind and source epoch, flag unsupported binaries/accelerating systems, expose propagation interval, and document model validity.

### Risk: coordinate-frame or observer-origin mistakes

**Mitigation:** use typed Astropy objects internally, include frame/origin/correction metadata in every result, and compare geocentric and topocentric fixtures.

### Risk: implicit network resources make results irreproducible

**Mitigation:** disable implicit downloads, support pinned local resources, hash file-backed inputs, and test offline execution.

### Risk: a user mistakes target generation for archive coverage

**Mitigation:** preserve the product boundary in CLI names, documentation, and result language; emit targets and candidate pointings, never “searched,” “complete,” or coverage claims.

### Risk: fixed corridor padding is mistaken for propagated covariance

**Mitigation:** distinguish assumed width from statistical uncertainty in the schema and require warnings when covariance is not propagated.

### Risk: stable IDs change because of incidental serialization details

**Mitigation:** define canonical science-input serialization, version it, use golden hash tests, and exclude paths and timestamps.

---

## 17. Open decisions before implementation freeze

1. Decide whether covariance propagation is a v1 release gate or a documented post-v1 enhancement; the schema must distinguish it either way.
2. Set quantitative tolerances and valid time spans for the baseline target and ephemeris models.
3. Choose the canonical file-backed JPL ephemeris fixture for release tests.
4. Decide whether VOTable is required for v1 or follows immediately afterward.
5. Decide whether the optional SIMBAD single-object helper ships in v1 or remains prototype-only.

None of these decisions changes the boundary excluding historical-coverage management.

---

## 18. Definition of success

SGLSETI v1 succeeds when a researcher can say:

> Using target solution X, geometry model Y, ephemeris Z, observer O, and relay range 550–2500 AU, these are the reproducible Rx and Tx regions at each requested historical or future epoch, with the listed assumptions and warnings.

The result must be usable as input to an external archive cross-match or commensal observing system, and another researcher must be able to reproduce it offline. SGLSETI itself makes no claim about what historical data exist or which observations searched the hypothesis.

---

## 19. References

1. Michaël Gillon, “A novel SETI strategy targeting the solar focal regions of the most nearby stars,” arXiv:1309.7586.
   <https://arxiv.org/abs/1309.7586>

2. Michael Hippke, “Interstellar communication network. III. Locating deep space nodes,” arXiv:2104.09564.
   <https://arxiv.org/abs/2104.09564>

3. Stephen Kerby and Jason T. Wright, “Stellar Gravitational Lens Engineering for Interstellar Communication and Artifact SETI,” arXiv:2109.08657.
   <https://arxiv.org/abs/2109.08657>

4. Nick Tusay et al., “A Search for Radio Technosignatures at the Solar Gravitational Lens Targeting Alpha Centauri,” arXiv:2206.14807.
   <https://arxiv.org/abs/2206.14807>

5. Gaia Data Release 1 documentation, “Astrometric source model.”
   <https://gea.esac.esa.int/archive/documentation/GDR1/Data_processing/chap_cu3ast/sec_cu3ast_intro.html>

6. Astropy Project, “Accounting for Space Motion.”
   <https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html>

7. ERFA, `starpm` source and routine documentation.
   <https://github.com/liberfa/erfa/blob/master/src/starpm.c>

8. NASA JPL, “Horizons System.”
   <https://ssd.jpl.nasa.gov/horizons/>

9. NASA NAIF, “SPICE.”
   <https://naif.jpl.nasa.gov/naif/>

10. European Space Agency, “Gaia Archive.”
   <https://gea.esac.esa.int/archive/>

11. Astropy Project, coordinates and time documentation.
   <https://docs.astropy.org/>
