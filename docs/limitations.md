# Limitations

What sglseti v1 does **not** do, and where its numbers stop being trustworthy.

## Scientific model

- **Approximate light time.** `tusay2022_eq5_7_v1` implements the published
  Tusay et al. (2022) eq. 5–7 approximation: ρ ≈ z, constant target
  distance, and Solar motion neglected during local light travel (~0.1″
  effect). It is not an iterative light-time solution and is never labeled
  one. Accuracy claims are arcsecond-class, regardless of library
  precision.
- **Linear stellar motion only.** Catalog propagation is linear space
  motion. Unresolved binaries and accelerating systems are *rejected at
  registry load* (flags `unresolved_binary`, `accelerating_system`;
  `endpoint_kind: other` unsupported); orbital endpoint models are a
  future, differently-named model family. Propagation spans beyond ±75 yr
  from the catalog reference epoch are flagged `long_propagation_span`.
- **No covariance propagation.** Widths on corridors, regions, and
  pointings are explicitly *assumed* pads, never propagated catalog
  covariance ([ADR-0001](adr/0001-v1-geometry-model.md)). Narrow-field
  scientific use requires an independently justified envelope.
- **Apparent products are approximate.** CIRS/AltAz come from astropy's
  frame machinery on finite-distance barycentric coordinates; they are
  validated for internal consistency (<0.5″ against an independent
  construction) but not against JPL Horizons. Refraction is never applied.
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
  relay-emission epoch retardation (~z/c, ≲0.1″-class), and
  impact-parameter uncertainty is not propagated — astrometric error
  displaces the axis by ~7×10⁻⁶ AU per arcsecond at 1 AU, which matters
  for sub-10⁻⁴ AU beam hypotheses.

## Product boundary

- **No archive knowledge.** sglseti computes where a hypothesis would
  appear; it does not know what data exist, was searched, or was covered —
  and its outputs never claim any of that.
- **No observation state.** No ledger, ingest, completion tracking,
  sensitivity records, or candidate management (CI-enforced boundary gate).
- **No scheduling.** Pointings are unscheduled candidate zones with
  grid-sampled validity windows; conflict-free sequencing, exposure
  planning, and telescope control belong to the observatory.
- **Circular fields only.** Irregular FOVs, MOC/ST-MOC output, and VOTable
  are post-v1.
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
  [benchmarks.md](benchmarks.md)); there is no parallel or distributed
  execution.
