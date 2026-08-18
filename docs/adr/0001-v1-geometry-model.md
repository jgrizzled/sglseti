# ADR-0001: v1 geometry model is `tusay2022_eq5_7_v1` with arrival-indexed catalog epochs

Date: 2026-08-17
Status: Accepted (machine-reviewed; human astrometry review remains a
release gate — see §Review)

## Context

The prototype (`sgl-search-planner`) implements the Tusay et al. (2022)
equations 6/7 role offsets (`rx: t−2z/c`, `tx: t+2d/c`) inside a private
helper. A strategy note had described the Rx target position via its
physical emission epoch (`t − 2z/c − d/c`), which appeared to conflict. The
reconciliation note (notes/sgl_light_time_epoch_reconciliation.md) resolved
this: the two descriptions use different time conventions — physical
barycentric state vs Gaia-style arrival-indexed catalog direction — and the
published offsets are correct *in the catalog convention*, which is also the
convention of Astropy/ERFA `apply_space_motion` (`starpm`). Subtracting the
additional `d/c` in the catalog convention double-retards the target.

Fetched confirmations (2026-08-17, arXiv:2206.14807 HTML): eq. 5
`P = S(t) − z·x(t)`; eq. 6 `tx: x(t + 2d/c)`; eq. 7 `rx: x(t − 2z/c)`;
probe placement restricted to a tenth of the Sun–star distance; neglected
Solar motion during Sun–probe light travel stated as an ~0.1″ effect.

## Decision

1. Ship exactly one v1 geometry model, named and versioned
   `tusay2022_eq5_7_v1` (1.0.0), with public roles `antipode`, `rx`, `tx`
   and catalog direction epochs `u = t_o`, `t_o − 2z/c`, `t_o + 2d/c`.
2. Interpret every catalog propagation epoch as an **SSB light-arrival
   epoch** (`catalog_epoch_semantics = ssb_light_arrival_time`). Physical
   target-event epochs are separate diagnostic outputs and are never passed
   to `apply_space_motion`.
3. Freeze the `DirectionSolution` field set and the four approximation
   flags (ρ=z, constant d, linear stellar motion, neglected Solar motion)
   as specified in docs/science/geometry_models.md §4; implemented as a
   frozen dataclass in `sglseti.models` guarded by a field-drift test.
4. Enforce validity bounds: `z > d/10` is invalid; `z` below the solar
   focal minimum (547.7576 AU) warns; propagation spans beyond ±75 yr from
   the catalog reference epoch warn.
5. **Covariance cut line:** v1 does not propagate catalog covariance. The
   minimum-acceptable option from the plan is adopted: outputs carry
   `uncertainty_method = not_propagated` plus a warning; region (DS9)
   output requires an explicit assumed half-width, labeled `assumed`.
   Rationale: honest labeling ships value now; the schema already
   distinguishes assumed vs propagated so adding propagation later is
   additive, not breaking.
6. Reserve `physical_state_*` / `iterative_lighttime_*` model-ID families
   for any future implementation that solves ρ, Solar motion, or light-time
   legs iteratively; v1 never describes itself as a full light-time
   solution.

## Fixtures independent of the prototype

Expected values live in `tests/data/reference/` and were produced by two
independent oracles (a stdlib-only first-principles propagator and a
straight-line astropy transcription of eqs. 5–7), not by the prototype. The
negative fixture `double_retarded_negative.yaml` encodes the double-retarded
Rx construction (31.6″ off in the synthetic case) and must always be
*detected*, never matched.

## Consequences

- Phase 4 implements the model against these fixtures; the geometry gate in
  the plan (§9.1) cites them directly.
- Every locus sample exposes both the catalog epoch and the approximate
  physical event epoch, so downstream users cannot confuse them silently.
- The ~0.1″ neglected-Solar-motion floor and the linear-motion assumption
  cap v1 accuracy claims at the arcsecond class regardless of library
  precision.
- Requests asking for DS9 regions without an assumed width fail validation
  once exports land (Phase 7).

## Review

Verification checklist (event ordering and signs; physical-vs-arrival epoch
distinction; ρ≈z reduction; ERFA `starpm` interpretation):

- [x] Machine review, 2026-08-17: fixtures cross-checked by two independent
  computational paths (stdlib-only physical propagation vs astropy catalog
  propagation transcribing the published equations); first-order offsets
  reproduced hand arithmetic (0.316″ = μ·2z/c and 63.25″ = μ·2d/c synthetic;
  0.064″ RA·cos δ Rx and 32.6″ total Tx for α Cen; 31.63″ = μ·d/c
  double-retarded offset). An independent adversarial review agent inspected
  signs, event ordering, and the ρ≈z reduction (findings recorded below).
- [ ] Human astrometry-aware reviewer sign-off — **required before the
  Phase 8 science release gate**; this ADR does not discharge plan §9
  gate 1.

### Independent machine review findings (2026-08-17)

An adversarial review agent (instructed to refute, working from its own
derivations, a fresh fetch of arXiv:2206.14807 §I.3.2 and of the ERFA
`starpm.c` source, and independent arithmetic) reported **no blocking
finding**. Summary of the record:

- CONFIRMED: Rx event chain and sign (u_rx = t_o − (ρ+z)/c, emission at
  u_rx − d/c; reduces to t_o − 2z/c, earlier than t_o, matching eq. 7
  verbatim) and Tx chain (arrival t_o + (z−ρ+d)/c, u_tx = t_o + (z−ρ)/c
  + 2d/c → t_o + 2d/c, later; the factor of two is re-indexing, not two
  flights).
- CONFIRMED: the double-retarded construction lands exactly where astropy's
  `apply_space_motion` puts the wrong-epoch direction (agreement 0.9 µas
  with the negative fixture); offset μ·d/c = 31.6250″ re-derived.
- CONFIRMED: ρ−z ≈ +(O−S)·â first-order relation and all frozen ρ values;
  |ρ−z| ≤ ~1.02 AU for terrestrial observers (1.1 AU bound sane); direction
  effect ~0.16–0.17 mas at μ = 10.4″/yr.
- CONFIRMED (high confidence): ERFA `starpm` propagates between observed
  places at SSB light-arrival epochs — verified from source text, the Gaia
  convention, and an empirical astropy-vs-physical-oracle cross-check
  agreeing to 1e-4–9e-4 mas over ~6-year spans (pre-demonstrating the
  Phase 4 equivalence test).
- CONFIRMED: every fixture value re-derived from scratch; both oracle
  scripts rerun and match the frozen YAML field-for-field; tolerances sane
  against stated error floors (with the fixture-acknowledged note that the
  2″ α Cen tolerance alone cannot catch an Rx epoch-sign error — that duty
  sits with the 1e-6 day epoch checks and the synthetic 0.316″ signature).
- REFUTED (docs prose only, all corrected in this commit): α Cen
  double-retardation illustration was ~16.3″, not "~7.6′"; the Sun-vs-SSB
  origin bound is ≲8 mas, not "<4 mas"; ADR sanity figure 32.4″ → 32.6″
  total; README fixture table was missing `barnard_scale_check.yaml`.
- Verdict: Phase 0 exit criteria stand; no frozen fixture value changed.
