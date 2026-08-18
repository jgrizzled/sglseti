# SGLSETI geometry models — v1 science specification

Status: Phase 0 implementation contract, frozen 2026-08-17.
Sources: [SGL Rx/Tx Light-Time Epoch Reconciliation](../../notes/sgl_light_time_epoch_reconciliation.md)
(the authoritative derivation), Tusay et al. 2022 (arXiv:2206.14807),
Gaia DR1/DR3 astrometric-model documentation, ERFA `starpm`.
Decision record: [ADR-0001](../adr/0001-v1-geometry-model.md).

## 1. Model registry

| model_id | version | status |
|---|---|---|
| `tusay2022_eq5_7_v1` | 1.0.0 | v1 baseline (this document) |

Reserved (not implemented, MUST NOT be claimed by v1): `physical_state_*`,
`iterative_lighttime_*` — names for future models that solve ρ, Solar
motion, and light-time legs with physical coordinate times. The v1 model
MUST NOT be labeled `full`, exact, or a light-time *solution*.

## 2. Conventions and notation

- Times: the requested epoch is the **observer reception epoch** `t_o`
  (UTC in, TDB used for propagation arithmetic).
- `z`: Sun–relay light-path length, approximated by the heliocentric relay
  distance. `ρ`: relay–observer light-path length. `d`: Sun–target
  light-path length, computed from the declared catalog parallax/distance.
- `a(u)`: the target's **arrival-indexed catalog direction** — the Gaia
  convention, where `u` is the light-arrival time at the SSB. Astropy's
  `SkyCoord.apply_space_motion(new_obstime=u)` propagates in exactly this
  convention (ERFA `starpm`).
- The Sun–SSB origin difference on the target direction is ≲ 8 mas at
  1.35 pc (the SSB sat ~2 R_sun from the Sun's center in 2021); it is part
  of the model's error budget, not separately corrected.
- `c` in AU/day: `299792458 × 86400 / 149597870700 = 173.144632674240`.
- Light propagation between local legs is flat-space; lensing bending is not
  applied to the travel-time scalars.

## 3. Role definitions (the frozen contract)

For model `tusay2022_eq5_7_v1`, the catalog direction epoch is:

```
antipode:  u = t_o
rx:        u = t_o - 2z/c
tx:        u = t_o + 2d/c
```

The relay locus and line of sight are:

```
P      = S(t_o) - z * a(u_role)          (Tusay eq. 5 with corrected epoch)
LOS    = unit(P - O(t_o))
```

with `S` the barycentric Solar position and `O` the barycentric observer
position, both at `t_o`.

### 3.1 Event bookkeeping behind the offsets

Before the ρ≈z reduction (reconciliation note §3):

| Role | Catalog (arrival) epoch `u` | Physical target event | Event kind |
|---|---|---|---|
| antipode | `t_o` | state seen near `t_o − d/c` | apparent_state |
| rx | `t_o − (ρ+z)/c` | emission at `t_o − (ρ+z+d)/c` | emission |
| tx | `t_o + (z−ρ)/c + 2d/c` | arrival at `t_o + (z−ρ+d)/c` | arrival |

With ρ≈z (an Earth observer and a relay hundreds of AU away), the rx epoch
reduces to `t_o − 2z/c` and the tx epoch to `t_o + 2d/c` — the published
equations 7 and 6.

**The cardinal rule:** the interstellar light time `d/c` belongs to the
*physical* emission epoch only. It is already implicit in an arrival-indexed
catalog direction. Passing the physical Rx emission epoch
(`t_o − 2z/c − d/c`) to `apply_space_motion()` double-retards the target and
shifts the direction by ≈ μ·d/c (31.6″ in the synthetic fixture; ~16.3″ for
α Cen). The negative fixture `double_retarded_negative.yaml` exists to catch
exactly this.

The Tx factor of two is one `d/c` to advance from the local epoch to the
physical arrival event plus one `d/c` to convert that physical event time
back into arrival-time coordinates; it is **not** two signal flights.

## 4. DirectionSolution — frozen field contract

`GeometryModel.target_direction(...)` returns a `DirectionSolution`
(defined in `sglseti.models`). Fields, frozen as of this document:

| Field | Meaning |
|---|---|
| `model_id`, `model_version` | model identity |
| `role` | antipode / rx / tx |
| `observation_epoch` | `t_o` (Time) |
| `catalog_direction_epoch` | `u` (Time) |
| `catalog_epoch_semantics` | fixed string `ssb_light_arrival_time` |
| `relay_event_epoch_approx` | `t_p = t_o − ρ/c` (Time) |
| `solar_lens_epoch_approx` | `t_ℓ` (Time) |
| `target_event_epoch_approx` | physical emission/arrival/apparent epoch (Time) |
| `target_event_kind` | emission / arrival / apparent_state |
| `target_light_time_days` | `d/c` |
| `sun_relay_light_time_days` | `z/c` |
| `observer_relay_light_time_days_approx` | `ρ/c` under ρ≈z |
| `target_direction_icrs_ra_deg/_dec_deg` | propagated catalog direction `a(u)` |
| `validity`, `warnings` | status; degraded/invalid never masquerades as valid |
| `rho_equals_z_assumed` | True for this model |
| `constant_target_distance_assumed` | True for this model |
| `linear_stellar_motion_assumed` | True for this model |
| `solar_motion_neglected` | True for this model (paper: ~0.1″ effect) |

Terminology rules (binding on code, docs, and output columns):

- `t_o − 2z/c` is never called an *emission epoch*; it is the catalog
  (SSB-arrival) direction epoch.
- Physical event epochs are diagnostics; they are never inputs to catalog
  propagation in this model.
- The four approximation flags are fixed True for this model and exist so
  future models can differ; they are not per-sample toggles.

## 5. Validity bounds and warnings

| Condition | Behavior |
|---|---|
| `z > d/10` | `invalid` (model bound stated by Tusay et al.) |
| `z < 547.7576 AU` (solar z_min) | warning `below_solar_focal_minimum` (geometry still computed; z_min from `solar_focal_distance.yaml`) |
| catalog propagation span `|u − reference_epoch| > 75 yr` | warning `long_propagation_span` (linear-motion degradation; preliminary bound) |
| missing radial velocity (flagged target) | warning `missing_radial_velocity`; perspective terms unmodeled |
| ephemeris out of coverage | `invalid`, no nominal row |

## 6. Preliminary numerical tolerances

Preliminary per Phase 0; revisited at the Phase 8 release gates.

| Check | Tolerance | Fixture |
|---|---|---|
| role-epoch arithmetic | 1e-6 day | `role_epoch_offsets.yaml` |
| solar z_min | 0.01 AU | `solar_focal_distance.yaml` |
| synthetic directions (both formulations) | 1 mas | `static_synthetic.yaml`, `constant_velocity_synthetic.yaml` |
| double-retardation detection | wrong construction ≥ 1″ away; offset ≈ μ·d/c ± 0.01″ | `double_retarded_negative.yaml` |
| high-PM scale/sign | 2 % of first-order offset | `barnard_scale_check.yaml` |
| eq. 5–7 reproduction vs reference script | 2″ | `alpha_cen_2021-11-06.yaml` |
| publication consistency (figure-read) | 15′ | `alpha_cen_2021-11-06.yaml` |
| ρ=z diagnostic | \|ρ−z\| ≤ 1.1 AU for terrestrial observers (report, don't fail) | α Cen + synthetic fixtures |

Known error floor of the model itself (not the implementation): neglected
Solar motion during local light travel ~0.1″; ρ≈z direction effect
≤ ~0.16 mas·(μ/10″yr⁻¹); linear-motion error grows with propagation span.
v1 therefore claims arcsecond-class, not sub-arcsecond, fitness. Published
tolerances must never claim better than these floors.

## 7. Uncertainty and covariance (v1 cut line)

Decision (ADR-0001): v1 does **not** propagate catalog covariance.

- Every locus sample carries `uncertainty_method = not_propagated` plus a
  warning, unless an explicit assumed width is configured, in which case the
  configured half-width is labeled `assumed`.
- DS9 region output (a width-bearing product) REQUIRES an explicit
  `uncertainty.assumed_half_width_arcsec` in the request; refusing to draw
  unlabeled-width regions is the honest failure mode.
- An `assumed` width is never described as catalog covariance, an error
  bar, or a confidence region in any output or doc.
- The registry schema gains an optional covariance block only when a
  propagating model exists (post-v1); `AstrometricState` stays as is.

## 8. Validation matrix (Phase 4 must implement)

1. Published-equation test → `alpha_cen_2021-11-06.yaml` (vs
   `tusay_eq57_reference.py` output).
2. Arrival-vs-emission equivalence → `constant_velocity_synthetic.yaml`.
3. No-double-retardation negative test → `double_retarded_negative.yaml`.
4. Zero-motion test → `static_synthetic.yaml` (roles share one direction;
   relay parallax remains range-dependent).
5. High-PM scale/sign → `barnard_scale_check.yaml`.
6. Local-leg diagnostic → ρ values frozen in the α Cen and synthetic
   fixtures.
7. Time-scale test → catalog-declared reference scale (Gaia TCB) must be
   honored; TCB/TDB confusion is a validation error, not a silent change.
   (Fixture lands with the ephemeris adapter in Phase 4.)
