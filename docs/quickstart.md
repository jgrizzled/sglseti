# Quick start

One epoch-neutral engine backs every workflow: historical target
generation for archive cross-referencing, commensal planning for
current/future observing, beam-crossing searches over past or future time
intervals, and the Python-level archival survey toolkit (last section).
All run fully offline once inputs are local.

Setup:

```bash
uv sync            # or: pip install -e ".[jpl]"
```

## Historical: loci for exact archive timestamps

Inputs: a curated target registry, a request, and an epoch table whose
`epoch_id` values are your join keys (see `examples/`).

```bash
sglseti validate targets examples/targets.yaml
sglseti validate request examples/historical.yaml
sglseti generate \
  --targets examples/targets.yaml \
  --request examples/historical.yaml \
  --output-dir build/archive-targets
```

Outputs land in `build/archive-targets/`: `samples.ecsv` (canonical),
`corridors.ecsv`, `result.json`, and `manifest.json`. Every row keeps its
input `epoch_id`, so joining back to your archive query loses nothing:

```python
from astropy.table import Table

samples = Table.read("build/archive-targets/samples.ecsv", format="ascii.ecsv")
mine = samples[samples["epoch_id"] == "archive-exposure-3"]
```

An external epoch table can also override the request's time mode:
`--epochs my_exposures.ecsv` (columns `epoch_id`, `time_utc`; extra columns
pass through as metadata).

## Commensal: a night of visibility and candidate pointings

```bash
sglseti samples --request examples/commensal-night.yaml   # dry sampling, no astronomy
sglseti plan \
  --targets examples/targets.yaml \
  --request examples/commensal-night.yaml \
  --output-dir build/commensal-night
```

Adds `visibility.ecsv` (altitude, Sun altitude, Moon separation, pass/fail
per grid epoch), `pointings.ecsv`/`.csv` (conservative circular candidate
zones with their radius components), and `regions.ds9`. Pointings are
candidate zones with valid windows — never a schedule.

## Crossings: when Earth passes through a hypothesized beam

A crossings request scans continuous time intervals — historical for
archival cross-referencing, current/future for commensal awareness — for
local minima of Earth's distance to each target's Sun-anchored beam axis
(inbound star→relay uplink at the apparent-state epoch, outbound
relay→star downlink at the tx aim epoch; ADR-0003):

```bash
sglseti validate crossings examples/crossings.yaml
sglseti crossings \
  --targets examples/targets.yaml \
  --request examples/crossings.yaml \
  --output-dir build/crossings
```

Outputs: `events.ecsv` (one row per closest approach: `t_ca_utc`, the
impact parameter `b_min_au`, side, transverse speed, and the two pointings
an observation would use — the star and the relay locus) and
`windows.ecsv` (ingress/egress per **assumed** beam radius, joined by
`event_id`), plus `result.json` and `manifest.json`. Feed the windows and
pointings to your archive query or schedule-intersection tool; sglseti
reports the impact parameter itself, never a detectability verdict.

For a schedule-holding consumer, the point query is cheaper than a scan:

```python
from astropy.time import Time
from sglseti import AstropyEphemeris, LinkDirection, Observer, impact_parameter

sample = impact_parameter(
    target=registry["barnard"],
    time=Time("2026-12-21T12:00:00", scale="utc"),
    link_direction=LinkDirection.INBOUND,
    observer=Observer.earth_center(),
    z_au=800.0,
    ephemeris=AstropyEphemeris(),
)
print(sample.b_au, sample.side)
```

## The same thing from Python

```python
from sglseti import (
    generate_loci,
    load_request,
    load_target_registry,
    plan_commensal,
    write_products,
)

registry = load_target_registry("examples/targets.yaml")
request = load_request("examples/commensal-night.yaml")
result = plan_commensal(generate_loci(request, registry), registry)
write_products(result, "build/commensal-night", generated_utc="2026-08-17T00:00:00+00:00")
```

Requests can also be built programmatically from the typed models
(`GeometryRequest`, `RelayRange`, `SamplingSpec`, …); see the API docstrings.

## Exit codes

`0` clean · `1` completed but with invalid status rows (see `validity` and
`warnings` columns) · `2` invalid input or domain error. `--strict` turns
any invalid row into a hard failure.

## Reproducibility

For citable products, pin the canonical ephemeris (see
[resources.md](resources.md)) and keep the emitted `manifest.json`: its
`science_input_hash` and the `calculation_id` identify the calculation
independently of paths and timestamps. A rerun from any directory, offline,
reproduces the same IDs and rows (this is CI-tested).

## Archival survey toolkit (Python API)

The batch workflows above cover point epochs; the survey-facing API adds
interval-aware, tolerance-driven, and uncertainty-aware products. See
[registry.md](registry.md) for the provider families these build on.

### Observation intervals as first-class requests

A request's time block may declare intervals instead of point epochs; each
materializes into labeled samples (`exp-1@start|mid|stop`, or a declared
subintegration grid), and every output row carries `interval_id`,
`interval_phase`, and `interval_duration_s`:

```yaml
time:
  intervals:
    - id: exp-1
      start_utc: 2015-09-04T23:30:00Z
      stop_utc: 2015-09-05T10:13:00Z
    - id: sector-11
      start_utc: 2019-04-23T00:00:00Z
      stop_utc: 2019-05-20T00:00:00Z
      subintegration_cadence_s: 86400.0
```

### The continuous locus and adaptive sampling

`evaluate_locus()` is the public continuous mapping
`(target, role, time, observer, z) → direction`; `adaptive_locus()` turns
it into an ordered polyline guaranteed within a caller-chosen angular
tolerance (tie it to your pixel scale, not a sample count), and
`covered_z_intervals()` refines your own footprint test — sglseti never
learns archive footprint schemas — into covered relay-distance intervals:

```python
from sglseti import RelayRange, Role, adaptive_locus, covered_z_intervals

locus = adaptive_locus(
    target=registry["barnard"],
    role=Role.RX,
    observation_time=t,
    observer=observer,
    relay_range=RelayRange(550.0, 2500.0),
    tolerance_arcsec=0.5,
    ephemeris=ephemeris,
    model=model,
)
covered = covered_z_intervals(
    target=registry["barnard"],
    role=Role.RX,
    observation_time=t,
    observer=observer,
    relay_range=RelayRange(550.0, 2500.0),
    contains=my_footprint.contains_radec,  # your WCS/footprint logic
    tolerance_arcsec=0.5,
    seed_step_arcsec=30.0,
    ephemeris=ephemeris,
    model=model,
)
```

`swept_locus()` builds a conservative envelope over an
`ObservationInterval`, and `interval_states()` reports position and motion
rates at its representative times.

### Propagated uncertainty (seeded, reproducible)

Registry entries carrying per-value uncertainties or covariance
(see [registry.md](registry.md)) can be propagated — Monte Carlo, with the
seed, sample count, and confidence level recorded on every product, and a
propagated confidence region always distinct from an assumed search pad:

```python
from sglseti import crossing_uncertainty, propagate_locus_uncertainty

sky = propagate_locus_uncertainty(
    target=target,
    role=Role.RX,
    observation_time=t,
    observer=observer,
    z_au=800.0,
    ephemeris=ephemeris,
    model=model,
    seed=42,
    count=256,
)
print(sky.confidence_radius_arcsec, sky.cross_track_sigma_arcsec)

dist = crossing_uncertainty(  # b_min / t_ca / v_perp distributions
    event=event,
    target=target,
    observer=observer,
    ephemeris=ephemeris,
    model=model,
    seed=42,
)
print(dist.b_min_lower_au, dist.b_min_upper_au, dist.side_consistency_fraction)
```

For a known schedule, `impact_parameter()` (point) and
`minimize_impact_parameter()` (over an `ObservationInterval`) avoid a
multi-year scan entirely.

### Observers beyond the ground

The request's observer block selects the family: `earth_center`, `site`,
`solar_system_body` (from the pinned ephemeris), `spacecraft_table` (a
checksummed ECSV ephemeris; supply velocity columns for cubic-Hermite
interpolation), `spacecraft_spice` (an SPK kernel via the `spice` extra),
or `programmatic` (a registered state function). File-backed observers
must pin `checksum_sha256`; identities carry content, never paths.

```yaml
observer:
  kind: spacecraft_table
  name: wise
  path: resources/wise_positions.ecsv
  checksum_sha256: sha256:...
```

### Archive scale: chunks and streaming

`plan_calculation()` + `iter_locus_chunks()` yield one corridor per
target/role/epoch in the documented product order — any chunk-index range
is independently reproducible with unchanged IDs, so parallel
orchestration stays downstream — and `write_samples_stream()` exports
row-by-row without materializing the full table:

```python
from sglseti import iter_locus_chunks, plan_calculation, write_samples_stream

plan = plan_calculation(request, registry)
write_samples_stream(
    (chunk.corridor for chunk in iter_locus_chunks(request, registry, plan=plan)),
    "build/survey",
    calculation_id=plan.calculation_id,
    model_id=request.model_id,
)
```

Add `votable` to a request's `products.formats` for `samples.vot` /
`events.vot` alongside the ECSV/CSV/JSON products.
