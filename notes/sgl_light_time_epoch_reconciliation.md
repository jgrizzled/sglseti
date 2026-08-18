---
title: "SGL Rx/Tx Light-Time Epoch Reconciliation"
date: 2026-08-17
status: "Resolved v1 science design note"
applies_to:
  - notes/seti_strategies_for_sgl_technosignatures.md
  - notes/sglseti_python_package_prd.md
  - sgl-search-planner/sgl_search/geometry.py
---

# SGL Rx/Tx Light-Time Epoch Reconciliation

## 1. Decision

The prototype's role epochs are scientifically consistent with equations 6 and 7 of Tusay et al. (2022):

    receiver    -> observation epoch - 2z/c
    transmitter -> observation epoch + 2d/c

They are not a role-label error, and the receiver expression is not missing an interstellar light time.

The apparent discrepancy came from using “target position” for two different quantities:

1. the target's **physical position at a remote emission or arrival event**; and
2. its **catalog astrometric direction indexed by light-arrival time at the Solar-System barycenter**.

Gaia astrometry and Astropy/ERFA catalog propagation use the second convention. In that convention, interstellar retardation is already implicit in the astrometric direction. Applying _SkyCoord.apply_space_motion()_ at the remote physical emission epoch would count the target–Solar-System light time a second time.

V1 will implement the published approximation as the explicitly named model _tusay2022_eq5_7_v1_. It will retain the public roles _antipode_, _rx_, and _tx_, expose the role-specific epochs and approximation flags, and not describe this model as a full light-time solution.

---

## 2. Source conventions

### 2.1 Tusay et al.

Tusay et al. define \(\mathbf{x}(t)\) as the target-star direction from the Sun and begin with the naive relay locus

\[
\mathbf{P}=\mathbf{S}(t)-z\mathbf{x}(t).
\]

Their key semantic point is that the star position seen at observation time \(t\) is already its apparent, retarded position. They derive

\[
\mathbf{P}\_{\rm tx}
=\mathbf{S}(t)-z\mathbf{x}(t+2d/c)
\]

and

\[
\mathbf{P}\_{\rm rx}
=\mathbf{S}(t)-z\mathbf{x}(t-2z/c).
\]

These are equations 6 and 7 of the paper.

### 2.2 Gaia astrometry

Gaia's standard stellar-motion model parameterizes a source by how it appears from the Solar-System barycenter (SSB). Its time argument is the time at which the source event would be observed at the SSB, after removing the observer-to-SSB Rømer delay—not the physical emission time at the star.

Write this catalog direction as

\[
\mathbf{a}(u),
\]

where \(u\) is an **astrometric arrival epoch**. To first order for a target at distance \(d\), \(\mathbf{a}(u)\) represents the direction to the target's physical state near

\[
u-d/c.
\]

### 2.3 Astropy/ERFA propagation

_SkyCoord.apply_space_motion()_ calls ERFA/SOFA catalog-propagation routines. ERFA's _starpm_ implementation propagates from an observed place at the first epoch to an observed place at the second epoch and accounts for the change in light time caused by radial motion.

For Gaia-like catalog parameters,

    coord.apply_space_motion(new_obstime=u)

therefore returns the catalog place associated with arrival epoch \(u\). It does not return the target's unretarded physical position at coordinate time \(u\).

---

## 3. Event-time derivation

### 3.1 Notation

Let:

- \(t_o\): time at which the terrestrial observer receives light from the local relay;
- \(t_p\): local relay event observed at \(t_o\);
- \(\rho\): relay-to-observer light-path length;
- \(z\): relay-to-Sun light-path length, approximated by heliocentric relay distance;
- \(d\): Sun-to-target light-path length, approximated by catalog distance;
- \(t\_\ell\): time at which the interstellar signal passes the Solar lens; and
- \(\mathbf{a}(u)\): target astrometric direction indexed by arrival epoch \(u\).

Ignoring relativistic corrections and path bending in the travel-time scalar,

\[
t_p=t_o-\rho/c.
\]

The derivation keeps \(\rho\) and \(z\) distinct before applying Tusay's \(\rho\simeq z\) approximation.

### 3.2 Receive role

For a local receiver, a remote signal travels

    target -> Solar lens -> local relay

and the light by which we observe the relay then travels

    local relay -> terrestrial observer.

The signal passes the Solar lens one Sun–relay light time before the relay event:

\[
t\_{\ell,{\rm rx}}
=t_p-z/c
=t_o-(\rho+z)/c.
\]

The incoming wavefront direction at that Solar event is the target's catalog direction with astrometric arrival epoch

\[
u\_{\rm rx}=t_o-(\rho+z)/c.
\]

The associated physical emission event at the target is approximately

\[
t*{e,{\rm rx}}
=u*{\rm rx}-d/c
=t_o-(\rho+z+d)/c.
\]

These are two descriptions of the same photons:

- a physical-state solver propagates a physical target state to \(t\_{e,{\rm rx}}\);
- a Gaia-like catalog solver propagates an arrival-indexed astrometric direction to \(u\_{\rm rx}\).

For an Earth observer and a relay hundreds of AU away, \(\rho\simeq z\). The catalog-direction expression becomes

\[
u\_{\rm rx}\simeq t_o-2z/c,
\]

which is Tusay equation 7 and the prototype's _receiver_ branch.

The interstellar term \(d/c\) appears in the physical emission epoch. It must not also be subtracted from the catalog direction epoch, because the catalog direction is already retarded by the target-to-SSB light time.

### 3.3 Transmit role

For a local transmitter, a signal travels

    local relay -> Solar lens -> target.

The Solar-lens passage is

\[
t\_{\ell,{\rm tx}}
=t_p+z/c
=t_o+(z-\rho)/c.
\]

The signal reaches the physical target approximately one interstellar light time later:

\[
t*{a,{\rm tx}}
=t*{\ell,{\rm tx}}+d/c
=t_o+(z-\rho+d)/c.
\]

To obtain that future physical state from an arrival-indexed catalog direction, solve

\[
u*{\rm tx}-d/c=t*{a,{\rm tx}},
\]

giving

\[
u\_{\rm tx}
=t_o+(z-\rho)/c+2d/c.
\]

With \(\rho\simeq z\), the local observer–relay and relay–Sun light times cancel:

\[
u\_{\rm tx}\simeq t_o+2d/c,
\]

which is Tusay equation 6 and the prototype's _transmitter_ branch.

The factor of two is not two future signal flights. One \(d/c\) advances from the local epoch to physical target arrival; the other converts that physical event time back to the arrival-time coordinate used by catalog astrometry.

### 3.4 Summary

| Role       | Physical target state represented | Catalog direction epoch   | Tusay approximation      |
| ---------- | --------------------------------- | ------------------------- | ------------------------ |
| _antipode_ | state seen near \(t_o-d/c\)       | \(u=t_o\)                 | \(\mathbf{x}(t_o)\)      |
| _rx_       | emission at \(t_o-(\rho+z+d)/c\)  | \(u=t_o-(\rho+z)/c\)      | \(\mathbf{x}(t_o-2z/c)\) |
| _tx_       | arrival at \(t_o+(z-\rho+d)/c\)   | \(u=t_o+(z-\rho)/c+2d/c\) | \(\mathbf{x}(t_o+2d/c)\) |

---

## 4. Source of the apparent conflict

The strategy note's physical description was sound: Rx photons were emitted at the target roughly one interstellar light time before reaching the Solar System, while Tx photons must reach a future target state.

Its implementation guidance was ambiguous because it said to propagate the target to the emission epoch without defining whether the propagation object was:

- a physical barycentric state \(\mathbf{r}\_\star(t)\); or
- a Gaia-like, arrival-indexed astrometric direction \(\mathbf{a}(u)\).

Those objects require different time arguments. V1 uses the second because it starts from catalog astrometric parameters. A future physical-state model may use the first, but the two conventions must not be mixed.

---

## 5. Assessment of the prototype

### 5.1 Correct and reusable

[GeometryEngine.\_direction_epoch()](../sgl-search-planner/sgl_search/geometry.py) correctly implements the published Tusay epoch offsets:

    if role == "receiver":
        return obstime - (2.0 * z_au * u.au / c).to(u.day)
    if role == "transmitter":
        distance = target_at_obstime.distance
        return obstime + (2.0 * distance / c).to(u.day)

[GeometryEngine.target_coord()](../sgl-search-planner/sgl_search/geometry.py) followed by _apply_space_motion()_ is conceptually compatible with an arrival-indexed catalog direction because Astropy uses ERFA catalog propagation.

### 5.2 Required changes in sglseti

The new implementation must not copy the prototype without these changes:

1. Name and version the model _tusay2022_eq5_7_v1_.
2. Document that _catalog_direction_epoch_ is an astrometric arrival epoch, not a physical target-event epoch.
3. Return both the catalog direction epoch and the inferred physical emission or arrival epoch.
4. Record the approximations \(\rho=z\), constant \(d\), linear stellar motion, and neglected Solar motion during local light travel.
5. Calculate \(d\) through a declared Sun–target or SSB–target approximation rather than silently reading a propagated coordinate's distance.
6. Require the target catalog's reference time scale. Gaia uses TCB; the prototype assigns TDB to every reference epoch.
7. Preserve Astropy/ERFA warnings and convergence status from space-motion propagation.
8. Warn or reject when the model-validity range is violated. Tusay restricts relay range to less than roughly one tenth of the target distance.
9. Reserve a different model ID for any implementation that solves \(\rho\), Solar motion, and the light-time legs iteratively.

---

## 6. Approximation scale

Useful scales for the proposed v1 search range are:

- \(1\,\mathrm{AU}/c \simeq 499.0\) seconds;
- \(2(550\,\mathrm{AU})/c \simeq 6.35\) days; and
- \(2(2500\,\mathrm{AU})/c \simeq 28.88\) days.

For Barnard's Star, using the prototype example's total proper motion of approximately \(10.39''\,\mathrm{yr}^{-1}\):

- the Rx target-direction correction is about \(0.18''\) at 550 AU and \(0.82''\) at 2500 AU;
- the Tx \(2d/c\) offset is about 11.93 years of propagated motion, or roughly \(124''\); and
- replacing exact \(\rho\) by \(z\) changes the time argument by at most about one AU of light time for an Earth observer, corresponding to at most about \(0.16\) mas from proper motion alone.

Thus the Rx correction matters for sub-arcsecond work, while the \(\rho\simeq z\) simplification is much smaller. Other approximations remain relevant: Tusay et al. estimate that neglecting Solar motion during the relay–Sun light time can change a relay position by order \(0.1''\).

These estimates are diagnostics, not v1 numerical acceptance tolerances.

---

## 7. V1 implementation contract

### 7.1 Model behavior

For model _tusay2022_eq5_7_v1_:

1. Interpret the requested epoch as observer reception epoch \(t_o\).
2. Interpret target catalog propagation epochs as astrometric arrival epochs.
3. Use:

   antipode: u = t_o
   rx: u = t_o - 2z/c
   tx: u = t_o + 2d/c

4. Construct the published first-order relay locus from the Solar position at \(t_o\).
5. Project the relay position from the selected observer at \(t_o\).
6. Label the result approximate even when coordinate transforms use high-precision libraries.

### 7.2 Output diagnostics

Each locus sample must expose:

- _observation_epoch_;
- _catalog_direction_epoch_;
- _catalog_epoch_semantics = ssb_light_arrival_time_;
- _relay_event_epoch_approx_;
- _solar_lens_epoch_approx_;
- _target_event_epoch_approx_;
- _target_event_kind = emission | arrival | apparent_state_;
- _target_light_time_;
- _sun_relay_light_time_;
- _observer_relay_light_time_approx_;
- _rho_equals_z_assumed_;
- _solar_motion_neglected_;
- target reference time scale and propagation-library version; and
- model ID and version.

### 7.3 Terminology

- Do not name \(t_o-2z/c\) the target emission epoch. It is the catalog-direction, or approximate Solar-arrival, epoch.
- Do not pass a physical target emission epoch to _apply_space_motion()_ for this model.
- Do not describe the Tusay model as a full finite-light-time solution.
- Reserve names such as _physical_state_ or _iterative_lighttime_ for models whose state provider and event equations use physical coordinate times consistently.

---

## 8. Validation requirements

1. **Published-equation test:** a direct implementation of Tusay equations 5–7 must match the model output.
2. **Arrival-versus-emission test:** a constant-velocity synthetic target must produce the same axis when calculated from:
   - a physical state at \(t*{e,{\rm rx}}\) or \(t*{a,{\rm tx}}\); and
   - the equivalent arrival-indexed catalog direction at \(u*{\rm rx}\) or \(u*{\rm tx}\).
3. **No-double-retardation test:** evaluating the catalog direction at the physical Rx emission epoch must differ by the expected extra \(d/c\) of proper motion and must not match the accepted fixture.
4. **Zero-motion test:** all roles share the same target direction when target transverse motion is zero; relay parallax remains range-dependent.
5. **High-proper-motion test:** Barnard's Star has the expected sign and approximate scale for Rx and Tx offsets.
6. **Published Alpha Centauri test:** reproduce the 2021 November 6 Tusay locus or pointings within documented catalog, ephemeris, observer, and approximation differences.
7. **Local-leg diagnostic:** compare \(\rho=z\) with a solved observer–relay range and verify the difference remains within the declared tolerance.
8. **Time-scale test:** use the catalog-declared reference scale and verify TCB/TDB conversion does not silently change stable model inputs.

---

## 9. Primary sources

1. Nick Tusay et al., “A Search for Radio Technosignatures at the Solar Gravitational Lens Targeting Alpha Centauri,” especially section I.3.2 and equations 5–7.
   <https://arxiv.org/html/2206.14807v1>

2. Gaia Data Release 1 documentation, “Astrometric source model,” defining the barycentric coordinate-direction time argument as light-arrival time at the SSB.
   <https://gea.esac.esa.int/archive/documentation/GDR1/Data_processing/chap_cu3ast/sec_cu3ast_intro.html>

3. Gaia DR3 documentation, “Reference systems and time scales,” describing the BCRS/TCB convention and observation-time interpretation for objects beyond the Solar System.
   <https://gea.esac.esa.int/archive/documentation/GDR3/Data_processing/chap_cu3ast/sec_cu3ast_intro/ssec_cu3ast_intro_refsystems.html>

4. Astropy documentation, “Accounting for Space Motion.”
   <https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html>

5. ERFA _starpm_ source and routine documentation, which propagate catalog data between observed places and explicitly solve the change in light time.
   <https://github.com/liberfa/erfa/blob/master/src/starpm.c>
