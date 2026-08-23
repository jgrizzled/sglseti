# ADR-0003: beam crossings use `sun_star_axis_v1` over the frozen role epochs

Date: 2026-08-18
Status: Proposed (machine-drafted; requires the same human astrometry
review as ADR-0001 before a science release that includes crossing
products)

## Context

The crossings feature answers: when does an observer (Earth center or a
terrestrial site) pass near the hypothesized beam of a target's relay
link, either the star-to-relay uplink or the relay-to-star downlink? The
products serve archival cross-referencing (which archives were looking at
the star or the relay locus while Earth sat inside a hypothesized beam)
and commensal awareness (will a telescope's epoch coincide with a
crossing). The strategy notes (§2.2, §5) require reporting the impact
parameter itself rather than a binary "crossing", because detectability
depends on beam width, annular illumination, wavelength, and receiver
properties this package does not model.

The geometry must reuse the reviewed `tusay2022_eq5_7_v1` catalog
propagation (ADR-0001) rather than invent a second astrometry path.

## Decision

1. **Axis.** The beam axis at observation epoch `t_o` is the line through
   the Sun's barycentric position along the role-propagated catalog
   direction `a(u_role)`. The observer's impact parameter is
   `b = |r − (r·a)a|` with `r = observer − Sun` (barycentric ICRS, AU);
   the signed along-axis distance `s = r·a` labels the side (`target` /
   `anti_target`).
2. **Link-direction epochs.** `inbound` (star→relay uplink) uses the
   apparent state `u = t_o` (`antipode` role): the light passing the
   observer at `t_o` is, physically, light arriving now, and arriving
   light travels along the apparent direction. `outbound` (relay→star
   downlink) uses the relay's aim direction `u = t_o + 2d/c` (`tx` role).
   Before the `ρ ≈ z` reduction its observer-time relation is
   `u = t_o + (z−ρ)/c + 2d/c`: relay emission at `t_o−ρ/c` followed by
   `z/c` propagation to the Solar lens leaves only the local
   `(z−ρ)/c` residual, not a separate full-`z/c` correction.
   Note the inbound epoch is *not* the `rx` role's `t_o − 2z/c`: that
   epoch indexes arrival at the relay, not at a ~1 AU observer.
3. **Declared approximations**, all first-order small against the beam
   radii of interest:
   - the axis is anchored at the Sun, not at the aim point or transmitter
     (the relay lies on the axis by hypothesis; transmitter aim offsets
     move the beam *center* by the aiming error, which is part of the
     consumer's beam hypothesis, not this geometry);
   - for `outbound`, the model's `ρ = z` reduction drops the local
     `(z−ρ)/c` term (≤ ~500 s for a terrestrial observer; direction effect
     `μ·|z−ρ|/c`, ≤ ~0.2 mas for `μ ≤ 10″/yr`). The full relay-emission
     delay is already paired with the relay-to-lens propagation above;
   - all `tusay2022_eq5_7_v1` approximation flags (linear stellar motion,
     constant target distance, neglected Solar motion) carry over. A
     direction error `δθ` displaces the axis at the observer by
     `≲ 1 AU · δθ` ≈ 7×10⁻⁶ AU per arcsecond — negligible against AU-scale
     impact parameters, relevant only for beam hypotheses below
     ~10⁻⁴ AU, where the not-propagated-uncertainty warning applies with
     force.
4. **Search.** Deterministic and offline: a coarse scan (default 10 d,
   validated ≤ 30 d — safely below the metric's semiannual structure)
   brackets minima; golden-section refinement locates each closest
   approach to a configured time tolerance (default 60 s); bisection
   solves ingress/egress for each **assumed** beam radius. Boundary
   minima (impact parameter still decreasing toward, or minimal at, an
   interval edge) are reported `degraded` with
   `minimum_at_interval_start/stop` — never hidden, never presented as
   clean closest approaches.
5. **Honest labeling.** Beam radii are caller hypotheses
   (`beam.radii_au`); windows state them explicitly. Impact-parameter
   uncertainty is not propagated in v1 (`uncertainty_method =
   not_propagated` + warning), matching the ADR-0001 covariance cut line.
   Events carry both the axis model identity (`sun_star_axis_v1` 1.0.0)
   and the direction model identity (`tusay2022_eq5_7_v1`), plus the
   target astrometry hash and ephemeris content identity.
6. **Boundary.** sglseti emits events, windows, and the two pointings an
   observation would use (the propagated star; the relay locus at the
   representative `z`). Archive lookup and telescope-schedule
   intersection remain external; `impact_parameter()` is the point-query
   API for schedule-holding consumers.

## Consequences

- Inbound and outbound axes differ by the proper motion over `2d/c`
  (tens of arcseconds for nearby high-proper-motion stars), i.e. by
  ~10⁻⁴ AU at the observer — distinct events for tight beam hypotheses,
  effectively coincident for wide ones. Both are first-class products.
- The `antipode`-epoch inbound axis means an inbound crossing observation
  points at the star's apparent position — exactly where a telescope
  would already point, which is what makes commensal eavesdropping cheap.
- Events inherit `tusay2022_eq5_7_v1` validity: `missing_radial_velocity`
  and `long_propagation_span` (deep archival intervals or large `2d/c`
  re-indexing) degrade events rather than silently passing.

## Review

- [x] Machine check, 2026-08-18: analytic circular-orbit fixtures
  (`tests/unit/test_crossings.py`) verify b_min = sin(latitude), one
  crossing per side per period at the correct epochs, window duration
  `2·asin(R)/ω`, transverse speed = orbital speed, and the μ·2d/c
  inbound/outbound axis separation; a builtin-ephemeris integration test
  re-verifies every reported minimum as a true local minimum of an
  independently recomputed metric.
- [ ] Human astrometry-aware reviewer sign-off on decisions 2 and 3
  (epoch choice per link direction; neglected-term bounds) — required
  before a science release gate that includes crossing products.
