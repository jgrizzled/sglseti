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

Release candidate. All v1 functionality is implemented and tested (see
`docs/release/v1-acceptance.md`); a final v1 tag awaits human
astrometry-review sign-off (`docs/adr/0001-v1-geometry-model.md`) and a
green CI platform matrix.

## Documentation

- [Quick start](docs/quickstart.md) — historical and commensal workflows
- [Conventions and product reference](docs/conventions.md) — frames, time
  scales, role epochs, every output column
- [Resources](docs/resources.md) — pinned ephemeris kernels and IERS, offline
- [Limitations](docs/limitations.md) — model validity and boundaries
- [Science specification](docs/science/geometry_models.md) and
  [ADRs](docs/adr/) — the reviewed `tusay2022_eq5_7_v1` contract
- [From the prototype](docs/from-the-prototype.md) — ported code provenance

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

## Usage

```bash
sglseti generate \
  --targets examples/targets.yaml \
  --request examples/historical.yaml \
  --output-dir build/archive-targets
```

or from Python:

```python
from sglseti import generate_loci, load_request, load_target_registry, write_products

registry = load_target_registry("examples/targets.yaml")
result = generate_loci(load_request("examples/historical.yaml"), registry)
write_products(result, "build/archive-targets",
               generated_utc="2026-08-17T00:00:00+00:00")
```

Every output row keeps its caller-supplied `epoch_id` join key, its
coordinate frame/origin/epoch semantics, model identity, resource
checksums, and validity status; a `manifest.json` separates the
deterministic science identity from run circumstance. See the
[quick start](docs/quickstart.md).

## Ephemeris resources

Calculations never touch the network. Astropy's built-in analytic ephemeris
works out of the box for exploration; reproducible scientific products
should pin the canonical kernel **JPL DE440s** (ADR-0002), fetched once with
the only network-using command:

```bash
sglseti fetch ephemeris de440s --output-dir resources/
# prints the verified sha256 and the request snippet:
#   ephemeris:
#     adapter: jpl_file
#     path: resources/de440s.bsp
```

`sglseti fetch iers --output-dir resources/` optionally downloads the
IERS-A Earth-orientation table as a pinned, checksum-identified file for a
request's `iers` block (sub-arcsecond effect on apparent/site products;
never required — without it, astropy's bundled tables are used and
identified in provenance). The `jpl_file` adapter needs the `jpl` extra:
`uv sync --extra jpl` or `pip install 'sglseti[jpl]'`.

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
