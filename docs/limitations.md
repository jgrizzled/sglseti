# Limitations

What sglseti v1 does **not** do, and where its numbers stop being trustworthy.

## Scientific model

- **Approximate light time.** `tusay2022_eq5_7_v1` implements the published
  Tusay et al. (2022) eq. 5–7 approximation: ρ ≈ z, constant target
  distance, and Solar motion neglected during local light travel (~0.1″
  effect). It is not an iterative light-time solution and is never labeled
  one. Accuracy claims are arcsecond-class, regardless of library
  precision.
- **Target motion is only as rich as the selected provider family.** The
  default `linear_astrometry_v1` family is rigid linear space motion:
  under it, the flags `unresolved_binary` and `accelerating_system` are
  *rejected at registry load*, and spans beyond ±75 yr from the catalog
  reference epoch are flagged `long_propagation_span`. Richer families
  exist and must be selected explicitly ([registry.md](registry.md)):
  catalog accelerations, two-body orbits for resolved binaries and
  barycenters (with their own declared approximations: tangential offset
  only, fixed angular semimajor axis, orbital RV neglected in epochs),
  and externally generated checksummed ephemerides (`sampled_state_v1`,
  the only family that models `planet` endpoints).
  `endpoint_kind: other` remains unsupported.
- **Batch product widths are assumed pads.** Widths on corridors, DS9
  regions, and pointings are explicitly *assumed* search pads, never
  propagated covariance ([ADR-0001](adr/0001-v1-geometry-model.md)).
  Propagated uncertainty exists as a separate, opt-in product family
  (`propagate_locus_uncertainty`, `crossing_uncertainty`): seeded Monte
  Carlo over the registry's declared uncertainties, with only the TARGET
  state propagated — observer-state, ephemeris, and model-floor
  contributions are labeled `not_propagated` (their measured floors are
  in [accuracy_budget.md](accuracy_budget.md)). The two kinds are never
  merged: a pad is never presented as a confidence region.
- **Apparent products are approximate.** CIRS/AltAz come from astropy's
  frame machinery on finite-distance barycentric coordinates; they are
  validated for internal consistency (<0.5″ against an independent
  construction). The GEOMETRIC ephemeris + observer + direction pipeline
  is cross-validated against JPL Horizons to ~0.01 mas
  ([accuracy_budget.md](accuracy_budget.md)); the apparent CIRS/AltAz
  transforms themselves are not Horizons-validated, and refraction is
  never applied.
- A missing radial velocity is either a load error or an explicit
  degraded-status propagation with RV = 0 — perspective effects are then
  unmodeled.
- **The focal threshold is ideal and geometric.** The finite-source
  photospheric threshold `z_min = f_inf·d/(d − f_inf)` marks where the Sun
  can focus the target's light at all; practical radio/optical observing
  limits lie farther out (solar atmosphere, corona, wavelength, required
  impact parameter) and are not modeled.
- **`z > d/10` is a search prior, not a physical bound.** It reproduces
  the Tusay et al. probe-placement restriction that controls the ρ ≈ z
  approximation error; beyond it results are `degraded`
  (`outside_search_prior`), and no independent error model replaces the
  prior.
- **Crossings report geometry, not detectability.** The
  `sun_star_axis_v1` impact parameter ([ADR-0003](adr/0003-crossing-axis-model.md))
  says how far the observer sits from the Sun-anchored beam axis; whether
  a signal would be seen depends on beam width, annular illumination, the
  SGL point-spread function, wavelength, transmitter aim and scan
  pattern, and receiver aperture — all outside the model. Beam radii in
  requests are assumed hypotheses; window durations are exact only for
  those assumptions. The outbound axis additionally neglects the
  relay-emission epoch retardation (~z/c; ~50 mas axis tilt at Wolf-359
  proper motion, see the accuracy budget). Scan events themselves carry
  `uncertainty_method = not_propagated`; use `crossing_uncertainty()` for
  distributions on `b_min`, the crossing time, and side-of-axis
  stability — astrometric error displaces the axis by ~7×10⁻⁶ AU per
  arcsecond at 1 AU, which matters for sub-10⁻⁴ AU beam hypotheses.

## Product boundary

- **No archive knowledge.** sglseti computes where a hypothesis would
  appear; it does not know what data exist, was searched, or was covered —
  and its outputs never claim any of that.
- **No observation state.** No ledger, ingest, completion tracking,
  sensitivity records, or candidate management (CI-enforced boundary gate).
- **No scheduling.** Pointings are unscheduled candidate zones with
  grid-sampled validity windows; conflict-free sequencing, exposure
  planning, and telescope control belong to the observatory.
- **Circular fields only.** Pointing grouping uses circular usable
  fields; irregular FOVs and MOC/ST-MOC output remain out of scope
  (footprint and coverage products belong to the survey consumer).
  For exact footprints, use `covered_z_intervals()` with your own
  containment test instead of pointing circles.
- Visibility numbers (geometric AltAz, inclusive thresholds) assist
  planning; they do not replace an observatory's pointing and refraction
  models.

## Operational

- Grids are sampled: windows and representative times are only as fine as
  the requested cadence, and constraint crossings between grid points are
  not solved for. Within a grid epoch, visibility does probe the corridor's
  angular extremes, and pointing radii include the drift envelope across
  the advertised window's grid epochs.
- The committed test kernel excerpt covers 2010–2035; full DE440s covers
  1849–2150. Epochs outside your kernel produce invalid rows by design.
- Performance is laptop-scale by requirement (see
  [benchmarks.md](benchmarks.md)); there is no in-package parallel or
  distributed execution. Chunked execution (`iter_locus_chunks`) is
  deterministic and independently reproducible per chunk-index range, so
  parallel orchestration is possible — downstream.

- Spacecraft observers interpolate caller-supplied tables (supply
  velocity columns; linear interpolation of coarse tables costs ~0.35″ at
  5-day nodes) or SPICE kernels (constant ~17 mas J2000/ICRS frame bias,
  declared). Their positions are inputs, not solutions — sglseti does no
  orbit determination.

Quantified magnitudes for every declared approximation and measured
floor are published in [accuracy_budget.md](accuracy_budget.md).
