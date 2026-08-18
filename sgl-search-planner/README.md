# SGL Search Planner

A small Python prototype for producing targeted telescope pointings for hypothetical
Solar Gravitational Lens (SGL) communication equipment, while retaining an auditable
record of which parts of the search space have already been observed.

The program is intentionally **target-list driven**. Routine planning reads a frozen
local target registry and never searches for "all nearby stars." An optional command can
resolve one explicitly named SIMBAD object to help create a registry entry, but those
values should be vetted and frozen before a real observing campaign.

## What the prototype does

- Models three local Solar System hypotheses for a selected remote system:
  - `receiver`: local equipment receiving through the Sun's gravitational lens.
  - `transmitter`: local equipment transmitting through the Sun's gravitational lens.
  - `antipode`: uncorrected anti-star line, useful as a comparison model.
- Propagates target astrometry with distance, proper motion, and radial velocity.
- Applies the approximate transmitter/receiver light-time geometry in Tusay et al.
  (2022), equations 5–7.
- Includes Earth-orbit parallax, observatory location, apparent CIRS coordinates,
  altitude/azimuth, Sun altitude, Moon separation, and predicted non-sidereal rates.
- Partitions only the target/range/role combinations named in a campaign file.
- Omits cells already complete for the campaign's exact search profile and geometry
  model.
- Groups adjacent missing cells into telescope pointings that fit a circular field of
  view.
- Emits CSV pointings, a DS9 region file, a results template, and a reproducibility
  manifest.
- Records completed observations in SQLite and enforces visit-count and cadence rules.

This is a planning and bookkeeping prototype, not an observatory-certified ephemeris.
See **Scientific limitations** below.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The optional one-object SIMBAD helper requires:

```bash
python -m pip install -e '.[catalog]'
```

## Core idea: partition physical hypothesis space, not nightly sky coordinates

A search cell is identified by:

```text
target system × local role × reciprocal-distance interval × partition version
```

Example:

```text
barnard.receiver.d3a736dbd2.0007
```

- `barnard` is the frozen target ID.
- `receiver` is the local terminal role.
- `d3a736dbd2` hashes the range-partition specification.
- `0007` is the cell index, ordered from larger to smaller heliocentric range.

The cell remains meaningful from night to night even though its RA/Dec changes because
of annual parallax and the modeled focal-line motion.

### Why reciprocal distance?

Let `z` be heliocentric range in AU and `q = 1/z`. For a one-AU observer baseline, the
parallax angle is approximately `q` radians. Uniform `q` cells therefore have roughly
uniform angular extent, which is much better matched to telescope fields of view than
uniform-AU shells.

For example, the full 550–2500 AU interval spans about 293 arcseconds in reciprocal
range before projection onto the particular sky direction. A 15-arcsecond partition
produces about twenty stable cells. A wide-field telescope can satisfy many cells with
one pointing; a narrow-field telescope uses several pointings without changing the
underlying bookkeeping grid.

## Configuration files

### `targets.yaml`

The target registry contains only systems deliberately selected for the campaign. Each
entry needs a coherent astrometric state:

```yaml
schema_version: 1

targets:
  barnard:
    display_name: "Barnard's Star"
    priority: 1.0
    tags: [tier1, single-star]
    notes: "Frozen, vetted astrometric solution."
    astrometry:
      ra_deg: 269.45207695861876
      dec_deg: 4.693364966576667
      parallax_mas: 546.9759
      pm_ra_cosdec_mas_per_yr: -801.551
      pm_dec_mas_per_yr: 10362.394
      radial_velocity_km_s: -110.11
      reference_epoch_jyear: 2000.0
      source: "Catalog citation and local snapshot ID"
```

For binaries, do not casually substitute one component's generic catalog row. Specify
which physical endpoint is hypothesized—component, barycenter, or outer-system node—and
use an orbital/barycentric ephemeris appropriate to the required precision.

### `campaign.yaml`

A campaign selects exact targets, roles, ranges, partitioning, telescope geometry,
night, observability constraints, and completion profile.

```yaml
schema_version: 1
campaign_id: "demo-kitt-peak-2026-12-15"
geometry_model: "tusay2022"
ephemeris: "builtin"
iers_auto_download: true

site:
  name: "Example site"
  longitude_deg: -111.6003
  latitude_deg: 31.9583
  elevation_m: 2096

night:
  start_utc: "2026-12-15T01:00:00"
  end_utc: "2026-12-15T13:00:00"
  grid_minutes: 10

instrument:
  telescope_id: "example-optical-01"
  fov:
    shape: "circle"
    diameter_arcmin: 8.0
    usable_fraction: 0.85
  corridor_half_width_arcsec: 20.0
  exposure_seconds: 300
  overhead_seconds: 60

constraints:
  min_altitude_deg: 25
  max_sun_altitude_deg: -12
  min_moon_separation_deg: 20

profile:
  profile_id: "optical-pulse-r-v1"
  signal_class: "optical-pulse"
  band: "r"
  required_successful_visits: 2
  min_visit_separation_days: 7
  min_quality: 0.8

selection:
  - target_id: "barnard"
    roles: [receiver, transmitter]
    range_au: {min: 550, max: 2500}
    partition:
      kind: "inverse_range"
      step_arcsec: 15
    include_cells: []
    exclude_cells: []

output:
  include_invisible: false
```

`include_cells` and `exclude_cells` accept exact stable cell IDs. Usually the target,
role, and range selections are sufficient; exact cell filters are useful for assigning
work among observatories or deliberately repeating a subset. Unknown IDs are treated as
configuration errors rather than silently producing an empty or incomplete campaign.

## Workflow

### 1. Inspect the stable cells

```bash
sgl-search cells --campaign examples/campaign.yaml
```

This command needs no Astropy calculations and prints cell IDs with their heliocentric
range bounds.

### 2. Inspect ledger coverage

```bash
sgl-search coverage \
  --targets examples/targets.yaml \
  --campaign examples/campaign.yaml \
  --ledger observations.sqlite
```

A cell counts as complete only when all of these match:

- exact `profile_id`;
- exact target/role/range cell;
- exact geometry-model hash, including the frozen astrometry, ephemeris setting,
  and assumed cross-track corridor width;
- required number of successful visits;
- minimum visit spacing;
- minimum quality.

If the target solution or geometry model changes, previous observations remain in the
ledger but do not silently satisfy the new model.

### 3. Generate the night's pointings

```bash
sgl-search plan \
  --targets examples/targets.yaml \
  --campaign examples/campaign.yaml \
  --ledger observations.sqlite \
  --output-dir run-2026-12-15
```

Outputs:

- `pointings.csv` — one row per conservative circular pointing zone.
- `pointings.reg` — DS9 regions: green search zone, cyan usable FOV, yellow range track.
- `observation_results_template.csv` — fill this after observing.
- `manifest.json` — model, dependency, configuration, and count metadata.

Important pointing fields include:

- ICRS geometric center and range-track endpoints;
- topocentric apparent CIRS RA/Dec at `best_time_utc`;
- altitude/azimuth, Sun altitude, and Moon separation;
- valid observing window on the configured time grid;
- predicted `dRA*cos(Dec)` and `dDec` rates;
- all stable cell IDs covered by the pointing.

The planner finds visibility windows and grouping, but v0.1 does not build a
slew-conflict-free sequence. Several rows may share the same best time. Schedule them
inside their reported windows or make the campaign window narrower around an intended
exposure time and rerun.

### 4. Record actual observations

Copy and fill the results template. Allowed status values are:

```text
success, failed, partial, aborted
```

Then ingest it:

```bash
sgl-search ingest \
  --plan run-2026-12-15/pointings.csv \
  --results run-2026-12-15/observation_results_template.csv \
  --ledger observations.sqlite
```

The ingest is idempotent for the same campaign, tile, cell, profile, model, and start
time. Re-ingesting updates the recorded outcome instead of adding another visit.

### 5. Generate the next night

Run `plan` with a new campaign night but the same target registry, partition, profile,
and ledger. Cells that have met the visit/cadence requirements are omitted.

## Optional: resolve one named SIMBAD object

This helper performs exactly one explicit object lookup and prints a YAML block:

```bash
sgl-search simbad --name "Barnard's star" --target-id barnard
```

It is deliberately not a nearby-star crawler. Treat the output as an import candidate,
not a final ephemeris. Freeze the source record, check its reference epoch, and replace
it with a system-specific barycenter or orbital solution where necessary.

## Coordinate model

At observation epoch `t`, let:

- `S(t)` be the Sun's barycentric position;
- `x(t)` be the propagated unit direction from the Sun to the remote system;
- `z` be the hypothetical relay's heliocentric range.

The prototype uses:

```text
antipode:    P = S(t) - z x(t)
transmitter: P = S(t) - z x(t + 2d/c)
receiver:    P = S(t) - z x(t - 2z/c)
```

where `d` is the remote-system distance. It then transforms the finite-distance
barycentric probe position to the configured terrestrial site and also calculates the
pure geometric topocentric line of sight for the ICRS search footprint.

The output circle includes the sampled range-track extent, a configurable corridor
half-width, and half an exposure's predicted motion.

## Reproducibility recommendations

For exploratory work, `ephemeris: builtin` is convenient. For real observations:

1. Use a pinned JPL SPK kernel or another validated ephemeris file.
2. Store its checksum with the campaign.
3. Cache and pin the IERS Earth-orientation table used for that night.
4. Record Astropy, ERFA, NumPy, and planner versions.
5. Keep the exact target registry under version control.
6. Bump `profile_id` whenever the band, signal-search pipeline, sensitivity threshold,
   cadence requirement, or completeness definition changes.
7. Compare several independently implemented ephemeris calculations before using a
   sub-arcsecond field of view.

The generated `manifest.json` captures the principal software/model identifiers, but a
production system should add checksums for external ephemeris and IERS files.

## Scientific limitations

The current prototype is intentionally conservative and limited:

- Linear stellar space motion is used. Binary orbital motion and hypothesized remote
  endpoint orbits are not modeled.
- The Tusay transmitter/receiver light-time treatment is an approximation, not a full
  null-geodesic or SPICE solution.
- Astrometric covariance is represented only through the manually configured corridor
  width; covariance propagation is not yet implemented.
- The search assumes actively maintained focal-line equipment. Historical/frozen
  relic tracks require an additional failure-epoch model.
- Only circular telescope fields are grouped automatically.
- Atmospheric refraction is disabled in Alt/Az calculations for numerical stability;
  the observatory control system should apply its own calibrated pointing/refraction
  model.
- The ledger records profile identity and quality, but v0.1 does not numerically compare
  heterogeneous limiting fluxes, pulse-energy thresholds, or radio EIRP limits.
- Arbitrary archival image footprints are not yet back-projected into physical cells.

## Recommended next extensions

1. **Astrometric covariance propagation.** Monte Carlo target state vectors and produce
   probability contours rather than a hand-set corridor width.
2. **Binary and endpoint ephemerides.** Add plugin models for component/barycenter orbits.
3. **Relic searches.** Add a failure epoch and passive post-failure orbit model.
4. **MOC/ST-MOC coverage.** Store actual irregular sky/time footprints using the IVOA
   Multi-Order Coverage standard, then project them back onto target/role/range cells.
5. **Sensitivity semantics.** Add typed thresholds for magnitude, fluence, flux density,
   bandwidth, drift-rate range, and duty cycle.
6. **Scheduling.** Add exposure duration, slew time, priority, airmass, and revisit
   constraints to produce a conflict-free sequence.
7. **Multiple observatories.** Keep one shared physical-cell ledger while allowing each
   telescope to generate its own nightly sky projection and FOV grouping.

## Tests

The partition and ledger tests do not require Astropy:

```bash
pytest -q tests/test_partition.py tests/test_ledger.py
```

The optional geometry smoke test runs when Astropy is installed:

```bash
pytest -q
```

## License

MIT. This prototype should be independently reviewed before use for telescope time.
