# Quick start

Two workflows share one epoch-neutral engine: historical target generation
for archive cross-referencing, and commensal planning for current/future
observing. Both run fully offline once inputs are local.

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
