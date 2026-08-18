# Quick start

Three workflows share one epoch-neutral engine: historical target
generation for archive cross-referencing, commensal planning for
current/future observing, and beam-crossing searches over past or future
time intervals. All run fully offline once inputs are local.

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
from sglseti import generate_loci, load_request, load_target_registry, plan_commensal, write_products

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
