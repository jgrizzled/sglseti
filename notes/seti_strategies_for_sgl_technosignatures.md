---
title: "SETI Strategies for Stellar-Gravitational-Lens Technosignatures"
date: 2026-08-17
status: "Technical notes, draft v0.2"
tags:
  - SETI
  - technosignatures
  - solar-gravitational-lens
  - observing-strategy
  - artifact-SETI
---

# SETI Strategies for Stellar-Gravitational-Lens Technosignatures

## Executive summary

A search for stellar-gravitational-lens (SGL) technosignatures is a strong SETI strategy because the hypothesis makes unusually specific predictions:

- **where** a Solar-System relay associated with a target star should appear;
- **how that apparent position changes** with date, observatory, assumed relay distance, and stellar proper motion;
- **when Earth or another observatory may cross** a hypothesized communications geometry;
- **which signal classes** are plausible for local control, optical trunks, waste heat, propulsion, or construction;
- **what motion a physical artifact should exhibit** over repeated observations.

The core program should therefore combine four products:

1. a reproducible SGL ephemeris engine;
2. multispectral observations of predicted local relay corridors;
3. scheduled observations of nearby stars during calculated beam-crossing windows;
4. a public, queryable observation-and-coverage ledger.

The ledger is essential. “This star has been searched” is not a meaningful scientific statement unless the record specifies time, sky footprint, assumed SGL distance, frequency, spectral and temporal resolution, drift range, pulse widths, sensitivity, polarization, signal morphology, and analysis pipeline.

---

## 1. Search hypothesis

The working hypothesis is:

> A technologically advanced interstellar network may place communication relays on or near the gravitational focal lines of stars, using one or two stellar lenses to reduce power and aperture requirements for links between neighboring systems.

For a target star \(S\), a conventional on-axis Solar relay lies approximately on the ray extending from \(S\) through the Sun and away from \(S\). For the Sun, the geometric focal line for rays that clear the photosphere begins near

\[
z_{\min}\simeq 547.8\ {\rm AU}.
\]

An engineered system may operate farther out to reduce coronal background or accommodate transmitter geometry. It may also use off-axis or sub-minimum-distance arrangements with reduced gain, so the search should distinguish a **baseline on-axis model** from broader speculative models.

The hypothesis predicts both:

- **local infrastructure signatures** near the anti-star focal corridor; and
- **interstellar-link signatures** near the target star or during a crossing of the associated beam geometry.

---

## 2. Search products

### 2.1 Live ephemeris service

The primary deliverable is software that answers:

> For a target star, date, observatory, relay-distance range, and link model, where on the sky should plausible transmit and receive nodes appear?

The output should be a **sky corridor or probability region**, not a single coordinate. The location depends on:

- assumed heliocentric relay distance \(z\);
- observatory position;
- observation time;
- Earth and Sun ephemerides;
- stellar position, parallax, proper motion, radial velocity, and covariance;
- finite light time;
- receive versus transmit geometry;
- point-ahead assumptions;
- optional stationkeeping and off-axis models.

Recommended inputs:

```text
target
observation_time
observatory
z_min
z_max
number_of_z_samples
link_role = rx | tx | both
confidence_level
astrometric_catalog
solar_system_ephemeris
model_version
```

Recommended outputs:

```text
target identifier and astrometric provenance
UTC and TDB epochs
observatory state
relay distance samples
ICRS RA/Dec locus
uncertainty envelope
Rx/Tx role
point-ahead vector
predicted angular rates
annual-parallax signature
target anti-proper-motion signature
DS9 region / VOTable / CSV / JSON export
```

### 2.2 Crossing-window service

A second product computes when Earth, another observatory, or a spacecraft passes near a hypothesized interstellar beam.

Recommended query:

```text
crossings(
    target,
    observer_body_or_site,
    time_start,
    time_end,
    link_direction,
    beam_model
)
```

Recommended output:

- closest-approach epoch;
- minimum perpendicular distance to the axis;
- distance in AU, kilometres, solar radii, and angular units;
- relative transverse velocity;
- event duration for several assumed beam radii;
- whether the observer is on the post-lens target side;
- Sun altitude and target visibility for selected observatories;
- uncertainties from stellar astrometry and model assumptions.

### 2.3 Observation planner

The planner combines predicted regions with telescope constraints:

- horizon and airmass;
- Sun, Moon, and bright-source avoidance;
- field of view;
- angular resolution;
- frequency coverage;
- instrument sensitivity;
- tracking rate;
- required cadence;
- crossing-window priority.

It should create observatory-ready target lists rather than static published coordinates.

### 2.4 Coverage ledger

Every observation and every search pipeline run is recorded. The ledger should support questions such as:

- Which Proxima SGL distances from 550 to 3000 AU have been imaged?
- Which fraction of the Alpha Centauri Rx corridor has been searched from 1–12 GHz?
- What optical pulse widths and repetition rates were tested?
- Which observations can constrain a 100 W continuous 1064 nm laser at 1000 AU?
- Which beam-crossing windows for Wolf 359 have simultaneous radio and optical coverage?
- Which raw datasets exist but have not been searched for drifting wideband signals?

---

## 3. Geometry of a local SGL corridor

### 3.1 First-order construction

Let

- \(\mathbf r_\odot(t)\) be the Solar-System barycentric position of the Sun;
- \(\mathbf r_\star(t)\) be the barycentric position of the target star;
- \(\hat{\mathbf n}(t)\) be the unit vector from the Sun toward the relevant apparent or predicted stellar position;
- \(z\) be the relay's heliocentric distance.

A first-order local relay location is

\[
\mathbf r_{\rm relay}(t,z)
=
\mathbf r_\odot(t)-z\hat{\mathbf n}(t).
\]

The apparent line of sight from observatory position \(\mathbf r_{\rm obs}(t)\) is

\[
\hat{\boldsymbol \ell}(t,z)
=
\frac{\mathbf r_{\rm relay}(t,z)-\mathbf r_{\rm obs}(t)}
{\left|\mathbf r_{\rm relay}(t,z)-\mathbf r_{\rm obs}(t)\right|}.
\]

Sampling \(z\) over a chosen interval produces a curved sky corridor because parallax depends on distance.

This approximation is adequate for exploratory plots. Precision scheduling should solve the finite-light-time problem.

### 3.2 Receive geometry

Two time conventions must be distinguished. Let:

- \(t_o\) be the epoch at which a terrestrial observer receives light from the relay;
- \(\rho\) be the relay–observer light-path length;
- \(z\) be the relay–Sun light-path length;
- \(d\) be the target–Sun light-path length; and
- \(\mathbf{a}(u)\) be a Gaia-like catalog direction indexed by light-arrival epoch \(u\) at the Solar-System barycenter.

The relay event we observe occurs approximately at \(t_p=t_o-\rho/c\). For a receiving node, the interstellar signal passed the Solar lens one relay–Sun light time earlier, so

\[
t_{\ell,{\rm rx}}
=t_o-(\rho+z)/c.
\]

The physical target emission represented by that wavefront occurred at

\[
t_{e,{\rm rx}}
=t_o-(\rho+z+d)/c.
\]

These epochs belong to different propagation models. A physical-state solver evaluates \(\mathbf{r}_\star(t_{e,{\rm rx}})\). A Gaia/Astropy catalog solver evaluates the already-retarded astrometric direction at

\[
u_{\rm rx}=t_{\ell,{\rm rx}}
=t_o-(\rho+z)/c.
\]

Under the Tusay et al. approximation \(\rho\simeq z\),

\[
u_{\rm rx}\simeq t_o-2z/c.
\]

The \(d/c\) term is implicit in the catalog direction and must not be subtracted again when using *SkyCoord.apply_space_motion()*. Doing so would double-retard the target.

The local receive node lies on the extension behind the Sun opposite the remote star's retarded incoming direction.

### 3.3 Transmit geometry

For a transmitting node, the local signal passes the Solar lens at

\[
t_{\ell,{\rm tx}}
=t_o+(z-\rho)/c
\]

and reaches the target's physical future position at

\[
t_{a,{\rm tx}}
=t_o+(z-\rho+d)/c.
\]

A physical-state solver evaluates \(\mathbf{r}_\star(t_{a,{\rm tx}})\). To represent the same physical state with an arrival-indexed catalog direction, its epoch must satisfy \(u_{\rm tx}-d/c=t_{a,{\rm tx}}\), hence

\[
u_{\rm tx}
=t_o+(z-\rho)/c+2d/c.
\]

With \(\rho\simeq z\), this becomes the Tusay et al. expression

\[
u_{\rm tx}\simeq t_o+2d/c.
\]

One \(d/c\) advances to physical signal arrival; the other converts that physical event time back to the arrival-time coordinate used by catalog astrometry.

The Tx and Rx axes can differ substantially for high-proper-motion stars because one references a past state and the other a future state.

The full derivation, assumptions, prototype assessment, and required diagnostics are recorded in [SGL Rx/Tx Light-Time Epoch Reconciliation](sgl_light_time_epoch_reconciliation.md). A future iterative physical-state solver should solve the light-time legs and moving Solar-System geometry consistently; it must not mix physical event epochs with arrival-indexed catalog epochs.

### 3.4 Point-ahead separation

For transverse relative velocity \(v_\perp\), a useful scale for the angular separation between incoming and outgoing axes is

\[
\Delta\theta_{\rm Tx-Rx}\sim \frac{2v_\perp}{c}.
\]

This is not a substitute for a full light-time solution, but it explains why permanent Tx and Rx installations may occupy separate corridors.

### 3.5 Relay-distance prior

The software should not hard-code a single distance. Recommended model families:

| Model | Distance range | Purpose |
|---|---:|---|
| Geometric minimum | \(547.8\) AU and above | hard lower bound for grazing solar rays |
| Baseline optical | \(600\)–\(2500\) AU | practical focal-line search |
| Extended | \(2500\)–\(10000\) AU | long-lived or low-background nodes |
| Off-axis/sub-minimum | configurable | reduced-gain speculative designs |
| Free outer relay | \(20\)–\(10000\) AU | non-lensed communication infrastructure |

Each published constraint must state which distance prior it covers.

### 3.6 Astrometric uncertainty

The target's catalog covariance should be propagated, not replaced by a single error radius. Recommended approach:

- sample the full Gaia astrometric covariance;
- include radial-velocity uncertainty where available;
- propagate each sample through the Rx or Tx light-time solver;
- include Solar-System ephemeris and observatory uncertainties;
- generate percentile sky envelopes;
- store both the nominal locus and the uncertainty region.

For stars with companions or poorly modeled acceleration, include an additional astrometric-acceleration term or use a fitted orbital solution.

---

## 4. Apparent motion of an artifact

A relay at \(z\) AU has annual parallax approximately

\[
p \simeq \frac{206265}{z}\ {\rm arcsec}.
\]

Examples:

| Range | Annual-parallax scale |
|---:|---:|
| 550 AU | 375 arcsec |
| 650 AU | 317 arcsec |
| 1000 AU | 206 arcsec |
| 2500 AU | 82.5 arcsec |
| 10000 AU | 20.6 arcsec |

This makes repeated imaging powerful. A physical candidate should show:

1. large Solar-System parallax;
2. a distance-consistent parallax ellipse;
3. secular motion tied to the negative of the target star's proper motion;
4. possible small non-Keplerian corrections from stationkeeping;
5. the correct Tx or Rx point-ahead offset.

A background star or galaxy will not satisfy this full motion model.

Recommended minimum cadence for an imaging candidate:

- two visits separated by hours or days to reject near-Earth and main-belt objects;
- three or more visits across different seasons to fit parallax;
- annual follow-up to test anti-target proper motion;
- multi-observatory parallax where possible.

---

## 5. Beam-crossing calculations

### 5.1 Axis-crossing metric

Let \(\hat{\mathbf n}(t)\) be the hypothesized outgoing axis from the Sun toward a target. For an observer at heliocentric position \(\mathbf r(t)\), the perpendicular distance to the axis is

\[
b_\perp(t)
=
\left|
\mathbf r(t)
-
\left[\mathbf r(t)\cdot \hat{\mathbf n}(t)\right]\hat{\mathbf n}(t)
\right|.
\]

The sign of \(\mathbf r\cdot\hat{\mathbf n}\) distinguishes the post-lens target side from the opposite side. A crossing search minimizes \(b_\perp(t)\) over time.

The software should report the impact parameter itself rather than declaring a universal “crossing,” because detectability depends on:

- beam width;
- annular illumination geometry;
- SGL point-spread function;
- receiver aperture;
- wavelength;
- transmitter scan pattern;
- whether the signal is direct, one-lens, or two-lens.

### 5.2 Duration

For effective beam radius \(R_b\) and relative transverse speed \(v_\perp\), a characteristic crossing time is

\[
\Delta t \sim \frac{2R_b}{v_\perp}.
\]

The search planner should produce event durations for a grid of assumed beam radii rather than one value.

### 5.3 Targets near the ecliptic

Stars near the ecliptic are especially valuable because Earth's orbit may pass close to the Sun–star axis. Wolf 359 has already motivated an optical search under this logic. The target ranking should include:

- minimum Earth-axis impact parameter;
- uncertainty in that impact parameter;
- number and timing of yearly windows;
- whether space observatories or other planets offer better crossings;
- target-star activity and background.

### 5.4 Simultaneous observations

During a high-priority crossing, observe:

- the target star;
- the predicted local SGL Tx corridor;
- the predicted local SGL Rx corridor;
- control fields;
- multiple frequency bands;
- multiple geographically separated observatories.

A coincident event with the predicted geometry, timing, drift, and moving local source would be far more compelling than an isolated transient.

---

## 6. Frequency strategy

The search should span microwave to X-ray, but observing time should be weighted by physical plausibility and detectability.

### 6.1 Radio and microwave: very high priority for local traffic

Approximate search range:

\[
0.1\ {\rm GHz}\ \text{to}\ 100\ {\rm GHz},
\]

with facility-dependent extensions.

Primary targets:

- local relay-to-inner-system telemetry;
- acquisition beacons;
- emergency control;
- broad or narrow direct links;
- leakage from power or digital systems.

Do not assume that a low-frequency detection must be the lensed trunk. The solar corona makes low radio frequencies unattractive for rays grazing the solar limb, but the same relay can use ordinary radio for local communications.

Search modes:

- narrow drifting carriers;
- broadband modulated emissions;
- cyclostationary features;
- repeated synchronization patterns;
- polarization anomalies;
- short bursts;
- dispersion inconsistent with an interstellar path for a source located in the outer Solar System.

### 6.2 Millimetre and sub-millimetre: high priority where available

Approximate range:

\[
100\ {\rm GHz}\ \text{to}\ 3\ {\rm THz}.
\]

This region offers better directivity and less solar-plasma degradation than centimetre radio, but instrumentation, atmospheric windows, and calibration are more difficult.

Search for:

- narrow carriers;
- frequency combs;
- coherent wideband modulation;
- unusual persistence at a moving SGL location.

### 6.3 Near-UV, visible, and near-IR: highest priority for trunk and acquisition

Approximate range:

\[
0.3\ \mu{\rm m}\ \text{to}\ 2.5\ \mu{\rm m},
\]

with UV extension from space.

Search modes:

- continuous ultra-narrow lines;
- nanosecond-to-second pulses;
- pulse trains;
- WDM-like clusters;
- frequency combs;
- phase-coherent polarization pairs;
- raster or acquisition sweeps;
- moving point sources in the predicted corridor.

The search should include both high spectral resolution and high time resolution. A conventional image stack can miss short pulses; a fast photometer can miss a narrow continuous line.

### 6.4 Far- and extreme-UV: targeted space-based priority

Some cool stars have low continuum emission in specific UV bands, potentially creating favorable signal-to-background windows. UV observations are also valuable because they test a region inaccessible to ground-based telescopes.

Challenges include:

- interstellar absorption;
- detector backgrounds;
- geocoronal emission;
- limited observing assets;
- stellar activity and emission lines.

### 6.5 Thermal infrared: high priority for infrastructure

Approximate range:

\[
3\ \mu{\rm m}\ \text{to}\ 100\ \mu{\rm m}.
\]

Primary targets:

- power plants;
- computation;
- propulsion;
- factories;
- radiators;
- warm dust from construction.

Thermal searches should not be limited to the exact focal corridor. Supporting infrastructure may sit in the Kuiper belt, inner Oort cloud, or on transport paths.

Look for:

- anomalously warm outer-system objects;
- non-asteroidal spectral energy distributions;
- stable temperatures inconsistent with passive equilibrium;
- moving mid-IR sources with SGL-compatible parallax.

### 6.6 X-ray: exploratory but scientifically defensible

Approximate range:

\[
0.1\ {\rm nm}\ \text{to}\ 10\ {\rm nm},
\]

depending on the observatory.

Possible targets:

- exotic communications;
- high-energy power transfer;
- compact high-power machinery;
- propulsion or acceleration events.

X-ray coverage is opportunistic because coherent sources and focusing architectures are less mature than optical systems, but an artificial narrow or periodically modulated source in a predicted corridor would be extraordinary.

### 6.7 Gamma ray: low-priority opportunistic search

Search archival event data for:

- repeated directionally consistent bursts;
- non-Poisson timing;
- narrow-energy features;
- events synchronized to predicted crossings.

This is a low prior compared with radio, optical, and IR, but it costs little when performed commensally on existing data.

---

## 7. Observation modes

### 7.1 Dedicated pointed observations

Point directly at sampled SGL corridors for the highest-priority nearby stars. Use mosaics or drift scans when the corridor exceeds the field of view.

### 7.2 Repeated astrometric imaging

Repeat observations over seasons to detect:

- annual parallax;
- anti-target proper motion;
- stationkeeping deviations;
- recurring glints or optical pulses.

### 7.3 Crossing campaigns

Concentrate multiwavelength resources around calculated minima in Earth-axis impact parameter. Include pre- and post-event baselines.

### 7.4 Commensal search

For every telescope pointing, automatically test whether the field intersects:

- a predicted SGL Rx corridor;
- a predicted SGL Tx corridor;
- an extended outer-relay region;
- a crossing event;
- a high-priority supporting-infrastructure region.

Record the incidental coverage even when no dedicated SETI pipeline runs.

### 7.5 Archival mining

Search existing radio, optical, UV, IR, X-ray, and gamma-ray archives. Important metadata include exact pointing, time, passband, time resolution, and data-product type.

### 7.6 Solar-system object surveys

Integrate SGL corridor predictions into moving-object pipelines. A relay may first appear as a faint trans-Neptunian candidate. Its motion model, not its brightness alone, is diagnostic.

### 7.7 Multi-baseline confirmation

Use separated observatories to test:

- near-field parallax;
- terrestrial interference;
- satellite contamination;
- wavefront arrival time;
- polarization consistency.

For a candidate at hundreds of AU, Earth's diameter creates small but potentially measurable differential geometry with sufficiently precise astrometry or timing.

---

## 8. Signal classes and search pipelines

Every observation should be associated with the signal classes actually tested.

### 8.1 Continuous narrowband

Parameters:

- frequency interval;
- channel width;
- drift-rate range;
- acceleration or jerk range;
- integration time;
- polarization;
- detection threshold.

### 8.2 Wideband digitally modulated

Parameters:

- occupied bandwidth;
- cyclostationary periods;
- symbol-rate range;
- entropy and compressibility tests;
- autocorrelation lag range;
- coherent de-dispersion assumptions;
- modulation-agnostic anomaly metrics.

### 8.3 Pulsed optical or radio

Parameters:

- pulse width;
- fluence threshold;
- repetition period;
- burst-cluster model;
- coincidence window;
- dead time;
- saturation behavior.

### 8.4 Frequency combs and multi-carrier systems

Parameters:

- line spacing;
- line-count threshold;
- allowed drift coherence;
- phase coherence;
- polarization structure;
- total occupied bandwidth.

### 8.5 Imaging and moving objects

Parameters:

- limiting magnitude or flux;
- point-spread-function model;
- angular-rate range;
- trail detection;
- glint duration;
- parallax model;
- ephemeris-fit residual threshold.

### 8.6 Thermal anomalies

Parameters:

- wavelength coverage;
- flux limit;
- temperature range;
- emissivity assumptions;
- motion constraints;
- background-source rejection.

### 8.7 High-energy event streams

Parameters:

- energy interval;
- localization error;
- timing resolution;
- periodicity range;
- burst morphology;
- coincidence with crossing windows.

A null result applies only to the rows of this signal-class space that the pipeline actually searched.

---

## 9. Candidate triage

### 9.1 Immediate checks

1. known satellites and spacecraft;
2. aircraft and terrestrial transmitters;
3. observatory artifacts;
4. known Solar-System objects;
5. cataloged stars, galaxies, masers, pulsars, and high-energy sources;
6. reproducibility in independent instruments;
7. consistency with predicted SGL position and motion.

### 9.2 High-value candidate features

A strong candidate may show several of the following:

- location inside a high-confidence Tx or Rx corridor;
- annual parallax consistent with \(550\)–\(10000\) AU;
- secular anti-proper-motion relative to the associated star;
- narrowband or pulsed emission;
- multi-frequency or multi-messenger coincidence;
- recurrence at predicted crossing windows;
- non-Keplerian stationkeeping;
- simultaneous local and target-star activity;
- persistence over months or years.

### 9.3 Follow-up ladder

**Level 0 — Instrumental/RFI review**

Reprocess raw data, inspect neighboring beams or detectors, and check local telemetry.

**Level 1 — Rapid repeat**

Repeat with the same facility and a second independent instrument.

**Level 2 — Motion and distance**

Measure parallax, angular rate, and orbit compatibility.

**Level 3 — Multispectral characterization**

Observe radio through IR; add UV or X-ray where justified.

**Level 4 — Coordinated global campaign**

Use multiple continents and space observatories; search both local corridors and remote star.

**Level 5 — In-situ mission planning**

For a persistent outer-Solar-System candidate, develop radar, occultation, or probe-intercept concepts while preserving planetary-protection and contamination controls.

---

## 10. Target prioritization

A practical priority score should be configurable rather than declared universal.

Suggested terms:

\[
{\cal P} =
w_d P_d+
w_c P_{\rm crossing}+
w_a P_{\rm astrometry}+
w_n P_{\rm network}+
w_b P_{\rm background}+
w_o P_{\rm observability}+
w_h P_{\rm historical\ coverage}.
\]

Where:

- \(P_d\): proximity of the target star;
- \(P_{\rm crossing}\): quality and frequency of Earth-axis crossings;
- \(P_{\rm astrometry}\): precision of position, proper motion, radial velocity, and companions;
- \(P_{\rm network}\): plausibility as a neighboring network node;
- \(P_{\rm background}\): stellar and coronal background;
- \(P_{\rm observability}\): telescope access, declination, and seasonal visibility;
- \(P_{\rm historical\ coverage}\): value of filling a poorly searched region.

Recommended target groups:

1. the nearest stellar systems;
2. high-proper-motion stars with accurately known astrometry;
3. stars near the ecliptic with favorable crossings;
4. isolated stars with simpler stationkeeping geometry;
5. systems with independent evidence of advanced technology;
6. stars that would be useful graph-theoretic neighbors in a local network;
7. control targets chosen to estimate false-positive rates.

---

## 11. Observation and coverage ledger

### 11.1 Why a ledger is necessary

A statement such as “Alpha Centauri was searched” omits nearly every scientifically important dimension. An observation may cover:

- one minute;
- one square arcminute;
- one SGL distance;
- one 100 MHz radio band;
- only sub-Hz tones;
- only a narrow drift-rate range.

It does not constrain optical pulses, wideband radio, infrared waste heat, X-ray events, other SGL distances, other epochs, or other signal morphologies.

### 11.2 Minimum observation record

Each observation should include:

| Dimension | Required metadata |
|---|---|
| Identity | observation ID, facility, instrument, program |
| Time | UTC start/end, exposure, cadence, timing accuracy |
| Pointing | ICRS footprint, tracking mode, angular response |
| SGL hypothesis | target, Tx/Rx/crossing/infrastructure, model version |
| Distance | relay-distance interval actually intersected |
| Spectrum | frequency or wavelength interval, resolution |
| Time domain | sample time, pulse-width sensitivity, dead time |
| Polarization | products recorded and searched |
| Sensitivity | flux/fluence/EIRP threshold with assumptions |
| Motion | angular-rate, Doppler-drift, acceleration coverage |
| Pipeline | software version, parameters, signal classes |
| Data | archive URI, checksum, access status |
| Result | null, candidates, exclusions, quality flags |
| Provenance | catalog, ephemeris, kernels, code commit |

### 11.3 Coverage is multidimensional

Define a coverage element as

\[
C =
C(
\text{target},
\text{role},
z,
t,
\Omega,
\nu,
\Delta\nu,
\Delta t,
\dot\nu,
\ddot\nu,
\text{polarization},
\text{signal class},
\text{sensitivity}
).
\]

A project may publish simplified two-dimensional maps, but the underlying record should remain multidimensional.

### 11.4 Coverage metrics

Useful metrics include:

- fraction of a sky corridor covered at a specified sensitivity;
- distance-weighted corridor coverage;
- logarithmic frequency coverage;
- total dwell time;
- number of independent epochs;
- fraction of a crossing window observed;
- sensitivity-volume equivalents;
- signal-class coverage;
- pipeline-completeness score;
- raw-data availability.

No single scalar should replace the full ledger.

---

## 12. Minimum viable observing program

### Phase A — Software and archival baseline

1. Implement reproducible Rx and Tx corridor calculations.
2. Publish predicted regions for the nearest 20–50 stellar systems.
3. Ingest existing SGL radio and optical searches.
4. Cross-match major public archives for incidental coverage.
5. Publish the first coverage dashboard.

### Phase B — Focused radio and optical survey

For the ten highest-priority stars:

- three or more epochs spread over one year;
- radio observations in several standard bands;
- optical high-resolution spectroscopy;
- fast optical photometry;
- moving-object imaging;
- simultaneous observations for at least one epoch.

### Phase C — Crossing campaigns

- calculate ten-year crossing windows;
- prioritize stars near the ecliptic;
- coordinate radio, optical/NIR, and high-energy observatories;
- observe local Tx/Rx corridors and the remote star simultaneously.

### Phase D — Thermal and artifact search

- mine mid-IR archives;
- obtain targeted deep IR observations of top corridors;
- search for motion and parallax;
- integrate with trans-Neptunian-object survey pipelines.

### Phase E — Persistent monitoring

- commensal alerts whenever a field intersects an SGL corridor;
- automated candidate scoring;
- annual regeneration from updated astrometry and ephemerides;
- open follow-up coordination.

---

## 13. Interpretation of null results

A null result should be written as a constrained hypothesis, for example:

> No persistent narrowband signal above \(F_{\min}\) was found between 1.10 and 1.90 GHz from the portion of the Alpha Centauri Solar Rx corridor corresponding to 550–1000 AU during the stated epoch, for drift rates between \(a\) and \(b\) Hz/s, under the pipeline and duty-cycle assumptions given.

It should not be written as:

> No Alpha Centauri relay exists.

Null results remain valuable because they accumulate in the ledger and close specific cells of parameter space.

---

## 14. Existing proof-of-concept searches

The strategy is not purely hypothetical.

- Gillon proposed monitoring the Solar focal regions of nearby stars for communication devices.
- Hippke developed calculations for apparent deep-space-node positions including parallax and proper motion.
- A Green Bank Telescope search targeted the Alpha Centauri SGL region in L and S bands and found no technosignature candidates.
- Optical observations searched the regions opposite Proxima and Alpha Centauri for continuous and pulsed laser emission.
- Wolf 359 was observed under the hypothesis that Earth may cross a relevant communication geometry.

These searches demonstrate feasibility while covering only small slices of time, frequency, distance, sensitivity, and signal morphology.

---

## 15. Program conclusion

A reasonable SGL SETI program is exactly:

1. calculate live Tx and Rx zones for nearby stars;
2. observe those zones from radio through high-energy bands, with emphasis on radio, optical/NIR, UV where available, and thermal IR;
3. calculate and observe favorable link-crossing windows;
4. maintain an open observation-and-coverage database.

The strongest addition is to make every calculation and null result **reproducible**. Each coordinate must be traceable to a catalog, ephemeris, time scale, relay-distance prior, and model version. Each search must state which signal classes it actually tested.

That turns the SGL-network hypothesis from an interesting SETI idea into a cumulative, falsifiable observing program.

---

## References and further reading

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

8. Slava G. Turyshev, “Light amplification by stellar gravitational lenses,” arXiv:2404.01201.  
   <https://arxiv.org/abs/2404.01201>

9. JPL Solar System Dynamics, “Horizons System.”  
   <https://ssd.jpl.nasa.gov/horizons/>

10. NASA Navigation and Ancillary Information Facility, “SPICE.”  
    <https://naif.jpl.nasa.gov/naif/>

11. European Space Agency, “Gaia Archive.”  
    <https://gea.esac.esa.int/archive/>
