# SGLSETI

SGLSETI is an open-source Python package that generates reproducible sky
targets for searches for solar gravitational lens (SGL) technosignatures. It
turns a curated stellar-system hypothesis, an observer, and past or future
epochs into telescope-usable SGL target regions.

One stateless, epoch-neutral engine supports two workflows:

- **Archival target generation** — calculate where an SGL relay hypothesis
  would have appeared at historical epochs so the positions can be
  cross-referenced with an archive by an external tool.
- **Commensal target generation** — calculate current or future positions,
  visibility, and simple circular-field pointings for use alongside another
  observing program.

## Product boundary

SGLSETI ends at the generation and export of target products (ECSV, JSON,
CSV, DS9 regions, and a provenance manifest). It does **not** query archives,
ingest observations, track historical search coverage, manage candidates, or
schedule telescopes. Those belong to external systems that consume SGLSETI
output.

## Status

Pre-release scaffold. The domain models, geometry engine
(`tusay2022_eq5_7_v1`), sampling, generation, planning, and export layers are
being implemented per `notes/implementation_plan.md`.

## Installation

Requires Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync          # create the virtual environment and install dependencies
uv run sglseti --help
```

Or with pip:

```bash
python -m pip install -e .
sglseti --help
```

## Planned usage

```python
from astropy import units as u
from astropy.time import Time
from sglseti import Observer, RelayRange, TargetRegistry
from sglseti.geometry import Tusay2022Eq57V1
from sglseti.generate import generate_loci

registry = TargetRegistry.from_yaml("examples/targets.yaml")
result = generate_loci(
    targets=[registry["barnard"]],
    epochs=Time(["2021-11-06T03:14:00"], scale="utc"),
    epoch_ids=["archive-exposure-1"],
    observer=Observer.from_geodetic(...),
    relay_range=RelayRange(550 * u.au, 2500 * u.au),
    roles=("rx", "tx"),
    model=Tusay2022Eq57V1(),
)
result.write_ecsv("loci.ecsv")
```

(API sketch from the PRD; names may be refined before v1.)

## Development

```bash
uv sync                 # installs the dev dependency group
uv run pytest           # unit / integration / regression tests (offline)
uv run ruff check .
uv run mypy
```

Default tests never require network access. See `CONTRIBUTING.md`.

## License

MIT — see `LICENSE`.
