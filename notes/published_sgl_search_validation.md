# Validating sglseti against published SGL technosignature searches

Date: 2026-08-18. Status: complete for the two known published searches.

Two SGL-targeted SETI campaigns have been published. This note records how
`sglseti` (v1.0.0rc, model `tusay2022_eq5_7_v1`) reproduces — or corrects —
their geometry. All computations used the astropy builtin ephemeris and the
bundled IERS tables; a from-scratch astropy cross-check (no sglseti imports)
confirmed every headline number.

## 1. Tusay et al. 2022 — GBT radio search at the SGL of Alpha Centauri

Paper: "A Search for Radio Technosignatures at the Solar Gravitational Lens
Targeting Alpha Centauri", AJ 164:116 (arXiv:2206.14807). GBT L/S band,
UT 2021 Nov 6, rx and tx loci along the α Cen antipode line, z = 550-1100 AU.

This is the package's native model: `tusay2022_eq5_7_v1` is a direct
implementation of their equations 5-7, and the repo already carries the frozen
anchor `tests/data/reference/alpha_cen_2021-11-06.yaml` (independent oracle:
`tusay_eq57_reference.py`). The paper tabulates no pointing coordinates — its
Figure 3 is the only published locus — so the fixture asserts 2" engine
reproducibility against the oracle plus 15' publication consistency against
the figure region. `pytest tests/regression/test_geometry_fixtures.py`:
28 passed (2026-08-18). The 2021 GBT session is not indexed in the
Breakthrough Listen open-data archive (queried 2026-08-18: no GBT files for
MJD 59523-59526, no SGL/antipode target names), so figure-level consistency
is the strongest available public check for this study.

## 2. Gillon, Burdanov & Wright 2022 — optical search for a Sun-SGL beacon transmitting to Wolf 359

Paper: "Search for an alien communication from the Solar System to a neighbor
star", MNRAS 513:L18 (arXiv:2111.05334). Hypothesis: a probe ("FICD") on the
Sun-Wolf 359 axis at 665 AU (beam impact parameter 1.1 R_sun) transmits an
optical beam toward Wolf 359; Earth crosses the beam annulus near solar
conjunction each early September. They imaged the antipodal field with
TRAPPIST-South (night of 2015 Sep 4-5) and SPECULOOS-South (2019 Sep 4-5).

This maps exactly onto sglseti's outbound-link crossing search: their
"aim where Wolf 359 will be, 2 x 7.86 ly of proper motion ahead" is the TX
role epoch u = t + 2d/c, and their ring geometry is
`crossings.sun_star_axis_v1` with `link_direction=outbound`,
`relay_distance_au=665`.

Inputs: Gaia EDR3 astrometry via SIMBAD (queried live 2026-08-18),
ICRS J2000-propagated: RA 164.1205036, Dec +7.0147231, pmRA* -3866.338,
pmDec -2699.215 mas/yr, plx 415.1794 mas, RV +19.57 km/s.

### Reproduced

| Quantity | Published | sglseti | Agreement |
|---|---|---|---|
| TRAPPIST-S pointing (antipodal field) | 22h56m20.81s, -06d59'28.4" | 22h56m20.94s, -06d59'28.4" (TX LOS, their epoch) | **2.0 arcsec** |
| Light-time PM correction (RA, Dec) | -59.9", -42.4" | -61.2", -42.4" (TX - antipode) | ~1" (their Dly/pm rounding) |
| Earth path impact parameter / annulus | 0.73 | 0.68-0.73 (b_min 0.74 R_sun 2015, 0.73 R_sun 2019, annulus 1.1 R_sun) | matches |
| Tangential (long) beam crossing | "~25 min in beam" | near-tangential confirmed (b_min inside annulus both years) | qualitative match |

### Discrepancy: the crossing epochs

| Epoch | Published crossing | sglseti minimum-b crossing | Offset |
|---|---|---|---|
| 2015 | JD 2457270.82 = Sep 5 07:41 UT | **2015-09-05 18:18 UT** | +10.6 h |
| 2019 | "around 1h45 UT" Sep 5 | **2019-09-05 18:46 UT** | +17.0 h |

The sglseti times are confirmed by an independent no-sglseti astropy
computation (minimize |r_earth-sun perpendicular to the PM-propagated
Sun->Wolf 359 axis|; agrees to ~15 min, the residual being the axis
direction epoch convention). At the paper's own stated crossing epochs the
Earth sits 1.85 R_sun (2015) and 2.76 R_sun (2019) off-axis — *outside*
their assumed 1.1 R_sun beam annulus — so their crossing times are
internally inconsistent with their own impact-parameter figure (0.73),
which our minimum-b reproduces. Their Sec. 3.1 pipeline is a hand-rolled
chain of equatorial<->ecliptic transforms with the of-date solar position;
the 2015 offset equals twice the accumulated equinox precession since J2000
expressed as Earth travel time (637 vs 640 min), suggesting a frame-mixing
error, but the 2019 offset (1021 vs 803 min) does not fit the same factor,
so the exact defect is not recoverable from two data points.

Observational consequence if sglseti is right: the true 2015 in-beam window
(annulus ingress/egress, ~±5 h around minimum) ran ~13:30-23:00 UT on Sep 5 —
daytime in Chile, starting ~3 h after the TRAPPIST run ended (10:13 UT), and
similarly outside the 2019 SPECULOOS run. The published null result would
then not actually constrain the beam-crossing hypothesis for those epochs.
Relevant to any archival crossing search: recompute crossing epochs with
`sglseti crossings`; do not inherit epochs from this paper.

### Reproduction

Validation scripts (session scratchpad, 2026-08-18) built the Wolf 359
target from the SIMBAD row above and ran:

- `find_crossings` with `CrossingsRequest(target_ids=("wolf_359",),
  link_directions=(OUTBOUND,), relay_distance_au=665.0,
  intervals=Aug-Oct 2015 and 2019, observer=earth_center,
  coarse_step_days=5, refine_tolerance_s=10)`
- `compute_relay_solution(role=Role.TX, z_au=665.0)` at the published 2015
  crossing epoch from the TRAPPIST-South site (-70.7403, -29.2563, 2347 m),
  compared against the published field center.

A frozen regression fixture now exists (added 2026-08-18):
`tests/data/reference/wolf359_crossing_reference.py` regenerates
`wolf359_crossing_reference.yaml`, and
`tests/regression/test_wolf359_crossing_fixture.py` asserts (1) engine
reproducibility against the independent oracle, (2) the crossing-epoch
disagreement as the explicit EXPECTED result, and (3) publication
consistency on the TRAPPIST-South pointing. The fixture uses the pinned
DE440s excerpt kernel rather than the builtin ephemeris used for the
table above; the kernel refines the off-axis distances at the published
epochs to 1.78 R_sun (2015) and 2.70 R_sun (2019) — still well outside
the 1.1 R_sun annulus, so the conclusion is unchanged.
