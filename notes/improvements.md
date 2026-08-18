---
title: "sglseti — Survey-Driven Improvements"
date: 2026-08-18
status: "v1.1 survey-readiness work complete; only gated and demand-driven items remain"
tags:
  - solar-gravitational-lens
  - astrometry
  - archive-survey
  - roadmap
---

# sglseti — Survey-Driven Improvements

## 1. Purpose

This note tracks the package improvements required by the first
archive-facing consumer, `sgl-seti-survey`. Everything needed before
publishing survey constraints has been implemented and verified; this
note now lists ONLY the remaining open items. Completed work (roadmap
items 6.1–6.12, 2026-08-18) is recorded in `CHANGELOG.md` and the git
history, and its reference documentation lives in:

- `docs/registry.md` — the registry schema and provider families;
- `docs/accuracy_budget.md` — the published accuracy budget (§2.5 gate);
- `docs/benchmarks.md` — archive-scale execution measurements;
- `docs/science/geometry_models.md`, `docs/adr/` — model contracts.

The product boundary is unchanged: `sglseti` owns versioned SGL geometry,
target and observer state propagation, uncertainty, generic target
regions, and reproducible exports. Archive discovery, observation ingest,
instrument footprints, signal searches, candidates, and coverage
accounting remain downstream responsibilities.

## 2. Open — gated

### 2.1 Higher-fidelity and broader hypothesis models

Gated deliberately: implement only after the baseline survey pipeline can
measure its own completeness (roadmap item 6.6). The declared model
approximations these would remove are quantified in
`docs/accuracy_budget.md` §6 (~11–50 mas class); none is material at the
published-search arcsecond regime.

- **Iterative physical-state and light-time model** — a separately named
  model family solving the light-time legs, observer-relay distance,
  Solar motion, and physical target state consistently. It must not
  silently replace the frozen Tusay approximation; use it to quantify
  where the v1 model ceases to meet an instrument-specific accuracy
  requirement.
- **Wavelength-aware focal and propagation models** — an explicitly
  selected model accounting for practical impact parameter, solar-corona
  limits, wavelength-dependent propagation, and a user-declared
  focal-distance prior. Outputs remain physical hypothesis parameters,
  not universal claims about detectability.
- **Endpoint-orbit and stationkeeping hypothesis families** — optional,
  separately versioned geometry families: communication aimed at a
  planet or an orbital uncertainty envelope rather than the host star;
  nominal station-kept relays with transverse or radial residuals; relay
  swarms around the nominal focal line; inactive relays on free
  trajectories. Separate versioning keeps a broad search from being
  confused with coverage of the baseline on-axis hypothesis. (A
  dedicated dynamical planet/moving-endpoint target provider belongs
  here too; `sampled_state_v1` already serves planet endpoints from
  external ephemerides.)

## 3. Open — demand-driven

Take up only when a concrete survey workload needs them (roadmap
item 6.13):

- **rx-role vectorized propagation inside the geometry model** — the
  measured dominant batch cost (antipode/tx catalog epochs are
  z-independent and fully cached; rx epochs `t − 2z/c` are not). Current
  throughput (~370 samples/s, `docs/benchmarks.md`) meets the survey
  requirement with margin.
- **Analytic or unscented-transform uncertainty path** — a fast
  alternative to the seeded Monte Carlo propagation; the MC path is
  ~1 s per 256-sample locus product today.
- **Observer-state and ephemeris uncertainty contributions** — currently
  declared `not_propagated` in every propagated product (honest labels;
  `docs/accuracy_budget.md` §5 shows both floors are far below target
  uncertainties for supported observers). Becomes worth revisiting if
  spacecraft ephemerides with material uncertainty enter the survey.
- **MOC/ST-MOC envelope export** — deferred: coverage products belong to
  the survey consumer (§5), and this would add a heavy dependency;
  revisit only for a concrete envelope-exchange need.
- **`other` endpoint kinds** — recognized by the registry schema,
  rejected at validation until a provider family models them.

## 4. Historical section map

In-code citations reference this note's original section numbers; all of
the following are DONE and documented as indicated:

| Old § | Topic | Where it lives now |
|---|---|---|
| §2.1 | pluggable target-state providers (linear / acceleration / two-body orbit / sampled) | `sglseti/providers.py`, `docs/registry.md` |
| §2.2 | registry schema: provenance, covariance, identifiers | `docs/registry.md` |
| §2.3 | propagated uncertainty products (Monte Carlo) | `sglseti/uncertainty.py` |
| §2.4 | observer-state providers (body / spacecraft table / SPICE / programmatic) | `sglseti/providers.py`, `docs/registry.md` |
| §2.5 | science gates: Wolf 359 fixture, Horizons validation, accuracy budget | `tests/regression/`, `docs/accuracy_budget.md` |
| §3.1 | observation intervals and swept loci | `sglseti/locus.py`, `intervals` request mode |
| §3.2 | continuous and adaptive corridor evaluation | `sglseti/locus.py` |
| §3.3 | uncertainty-aware crossings, spacecraft observers, point/interval APIs | `sglseti/uncertainty.py`, `sglseti/crossings.py` |
| §3.4 | vectorized, chunked, cache-aware execution | `docs/benchmarks.md`, `benchmarks/archive_scale.py` |
| §3.5 | product and provenance extensions (result schema v3) | row/manifest provider identity, intervals, VOTable |
| §4 | higher-fidelity and broader hypotheses | OPEN — §2 above (gated) |
| §6 | implementation order (items 1–13) | items 1–5, 7–12 done; 6 gated; 13 demand-driven |

Adjacent decision of record: the greenfield identity baseline
(2026-08-18) — canonical schema v2, single registry schema, required
content checksums on file-backed specs — adopted before first
operational use; see `CHANGELOG.md`.

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
