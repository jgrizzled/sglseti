# Accuracy budget

Geometric ICRS pointing-error budget for the v1.1 stack (improvements
§2.5), by model, observer type, epoch span, and target-state provider.
Measured entries were computed 2026-08-18 on the pinned DE440s excerpt
kernel and are pinned by `tests/regression/test_accuracy_budget.py` and
the Horizons validation suite, so the numbers cannot silently drift from
the code. Scaling laws are given so the budget transfers to
configurations not tabulated here.

Three error classes are kept separate throughout the package and in this
document:

- **Declared model approximations** — systematic by design, attached to a
  named model version, never silently improved;
- **Implementation and resource floors** — measured, far below the
  approximations;
- **Input (catalog) uncertainty** — not an error of the package;
  propagated on request (§2.3) and reported with seeds and confidence
  levels.

Reference configurations: z = 550–2500 AU; Wolf 359
(μ = 4.72 arcsec/yr, 2d/c = 15.7 yr) and Alpha Cen (2d/c ≈ 8.7 yr) as
fast/near extremes. Rule of thumb used below: a transverse displacement
δ of the observer or relay maps to pointing error δ/ρ, with
ρ ≈ z (1 AU at 550 AU ≡ 6.3 arcmin; 0.01 AU ≡ 3.76 arcsec, measured).

## 1. By model

### `tusay2022_eq5_7_v1` (v1.1.0) — declared approximations

| Approximation | Scaling | Magnitude | Notes |
|---|---|---|---|
| Solar motion neglected during Sun–relay light travel | ≤ v☉/c, independent of z | **≤ ~11 mas** (measured solar barycentric speed ≤ 16 m/s) | Same physics class as the measured 9 mas light-time residual in the Horizons validation; the source paper's stated ~0.1 arcsec is a conservative bound |
| ρ = z (observer–relay ≈ Sun–relay distance) | rx/tx omit the catalog-epoch correction (z−ρ)/c; \|z−ρ\|/c ≤ ~500 s → μ·Δt | **≤ ~0.1 mas** even at Wolf 359 proper motion | Relay-emission `−ρ/c` and relay-to-lens `+z/c` combine to this residual for tx; no full `z/c` term is missing. Also drives the `observer_relay_light_time_days_approx` diagnostic |
| Constant target distance during propagation | δd = v_r·Δt → tx epoch error 2δd/c | sub-mas for all registry targets at ±75 yr | |
| Linear stellar motion | see §3 (epoch span) | dominates the budget for binaries/accelerating targets | Removed by the richer provider families (§4) |
| z > d/10 search prior | n/a — flagged, not an error | rows degrade with `outside_search_prior` | Study prior, not a physical bound |

### `sun_star_axis_v1` (crossings) — declared approximations

| Approximation | Scaling | Magnitude (Wolf 359, z = 665 AU) |
|---|---|---|
| Outbound observer-distance residual inherited from ρ = z | before the reduction, `u_tx = t_o + (z−ρ)/c + 2d/c`; v1 drops `(z−ρ)/c` | same ≤ ~0.1 mas bound above → ≤ ~5×10⁻¹⁰ AU (≤ ~1×10⁻⁷ R☉) on b at s ≈ 1 AU |
| Closest-approach refinement tolerance | request `refine_tolerance_s` (default 60 s; 10 s in fixtures) | t_ca resolution only |
| Transverse-speed finite difference | 1 h central step | diagnostic-only quantity |

## 2. By observer type

| Observer family | Contribution | Magnitude |
|---|---|---|
| `earth_center_v1` | ephemeris only (below) | — |
| `terrestrial_site_v1` | topocentric parallax vs geocenter (real signal, modeled) | up to ~16 mas at z = 550 AU (measured 1–20 mas) |
| | site GCRS construction floor | **0.009 mas** measured vs Horizons topocentric |
| `solar_system_body_v1` | ephemeris only | — |
| `spacecraft_table_v1` | displacement vs Earth is the modeled signal: δ/ρ | 0.01 AU at 550 AU ≡ **3.757 arcsec, measured = predicted** |
| | cubic-Hermite interpolation (velocity columns), h-day nodes, Earth-like orbit | (h⁴/384)·ω⁴ AU → **~0.05 mas at h = 5 d**, z = 550 AU |
| | linear interpolation (no velocities) | (h²/8)·ω² AU → **~0.35 arcsec at h = 5 d** — supply velocities or use ≲ 1-day nodes |
| `spacecraft_spice_v1` | SPICE J2000 vs ICRS frame bias (constant, declared) | ~17 mas |
| `programmatic_observer_v1` | caller-owned | declared via `identity` |

## 3. By epoch span (linear family degradation)

The ±75 yr `long_propagation_span` bound exists because unmodeled motion
grows quadratically. Worked example — Barnard's Star perspective
acceleration (~1.3 mas/yr², from 2μv_r/d):

| Span from reference epoch | Unmodeled offset 0.5·a·t² |
|---|---|
| 10 yr | ~65 mas |
| 30 yr | ~0.6 arcsec |
| 75 yr | ~3.6 arcsec |

Role epochs AMPLIFY the span: the tx aim epoch is u = t + 2d/c, so
catalog-parameter errors act over the extended span. Verified scaling
(pinned by the budget test to 1%): the tx–antipode direction offset for
Wolf 359 is μ·2d/c = **74.1 arcsec measured vs 74.09 predicted**. A
proper-motion uncertainty δμ therefore contributes δμ·(t − t_ref + 2d/c);
Gaia-class δμ ≈ 0.1 mas/yr over Wolf 359's tx span ≈ **~2 mas** — use
propagated uncertainty (§2.3 products) rather than this table for real
error bars.

## 4. By target-state provider

| Family | Removes from the budget | Own residuals |
|---|---|---|
| `linear_astrometry_v1` | — (baseline) | all of §3 for accelerating/orbital endpoints |
| `acceleration_astrometry_v1` | quadratic term (e.g. the §3 example) | higher-order terms; jerk ~ a·(v/d)·t³ scale, negligible ≤ 75 yr |
| `two_body_orbit_v1` | component orbital motion (α Cen A amplitude ≈ 8.2 arcsec — the largest single term in this budget) | tangential-offset-only (orbital LOS displacement ~23 AU on d ≈ 2.8×10⁵ AU: ~10⁻⁴ relative); orbital RV neglected in epochs; fixed angular semimajor axis; element errors propagate via §2.3 |
| `sampled_state_v1` | whatever the external ephemeris models | interpolation floors as for spacecraft tables (§2); table cadence is the caller's accuracy dial; wrong-file guard at 1 deg |

## 5. Resource and implementation floors (measured)

| Floor | Measured | Where pinned |
|---|---|---|
| Pinned JPL kernel vs Horizons DE441 (Sun/Earth vectors) | sub-meter | `test_horizons_validation.py` |
| Builtin analytic ephemeris vs Horizons (absolute barycentric) | ≤ ~119 km | same |
| Builtin vs kernel **relay pointing** | **≤ 0.02 mas** at z = 550–2500 AU | budget test |
| Ephemeris + observer + direction pipeline vs Horizons (light-time applied) | 0.002 / 0.009 mas (geocenter / site) | `test_horizons_validation.py` |
| Neglected light-time class (geometric vs astrometric solar direction) | ~9 mas measured; theoretical bound v☉/c ≈ 11 mas | same + budget test |
| Earth-orientation (apparent CIRS/AltAz and visibility only) | sub-mas with in-coverage IERS-A; up to arcsec-level with 50-yr-mean polar motion — always warned, never silent | `test_iers_handling.py` |
| Monte Carlo summary statistics | ~σ/√N (seeded, deterministic) | recorded per product |

The relay-pointing floor is far below the absolute ephemeris difference
because the locus and impact-parameter constructions depend on the
Earth–Sun RELATIVE vector, in which the analytic series' shared
barycentric error cancels.

## 6. Reading the budget

For arcsecond-class pointing (the published-search regime), every floor
and model approximation is ≥ 100× below requirement **except**:

1. unmodeled binary/accelerating motion under the linear family (§3, §4)
   — select the appropriate provider family;
2. spacecraft displacement itself (§2) — a modeled signal, not an error,
   but it must not be ignored (0.01 AU ≡ 3.76 arcsec at 550 AU);
3. linear interpolation of coarse spacecraft tables — supply velocity
   columns;
4. catalog uncertainty over amplified tx spans — propagate it (§2.3).

For milliarcsecond-class work, the ≤ ~11 mas solar-motion class and ~17 mas
SPICE frame bias become material. The terrestrial outbound
observer-distance residual remains ≤ ~0.1 mas even at Wolf-like proper
motions, but should likewise be retained by a sub-mas model. These terms
are attached to model versions and await the §4.1 higher-fidelity family
(roadmap item 6.6) rather than silent fixes.
