# SGLSETI

SGLSETI is an open-source Python package that generates reproducible sky
targets for searches for solar gravitational lens (SGL) technosignatures. It
turns a curated stellar-system hypothesis, an observer, and past or future
epochs into telescope-usable SGL target regions — with versioned geometry
models, explicit uncertainty, and content-hashed provenance on every row.

One stateless, epoch-neutral engine supports the core workflows:

- **Archival target generation** — calculate where an SGL relay hypothesis
  would have appeared at historical epochs (instantaneous, or as
  first-class observation intervals with start/mid/stop samples) so the
  positions can be cross-referenced with an archive by an external tool.
- **Commensal target generation** — calculate current or future positions,
  visibility, and simple circular-field pointings for use alongside another
  observing program.
- **Beam-crossing search** — scan past or future time intervals for the
  moments an observer passes closest to a target's hypothesized relay beam
  axis (inbound uplink or outbound downlink), reporting impact-parameter
  events and assumed-beam-radius windows (`sglseti crossings`, ADR-0003) —
  plus cheap point/interval queries for joining a known schedule.
- **Archival survey toolkit (Python API)** — the continuous locus
  evaluator and tolerance-guaranteed adaptive sampler, swept envelopes
  over observation intervals, covered relay-distance refinement against a
  caller-supplied footprint test, seeded Monte Carlo uncertainty
  propagation (sky regions, crossing distributions, side-of-axis
  stability), and deterministic chunked execution with bounded-memory
  streaming export for archive-scale runs.

## Modeled physics, explicitly versioned

- Geometry: the reviewed `tusay2022_eq5_7_v1` role model (Tusay et al.
  2022 eq. 5–7) and the `sun_star_axis_v1` crossing-axis contract, with
  every approximation declared per row and quantified in the
  [accuracy budget](https://github.com/jgrizzled/sglseti/blob/main/docs/accuracy_budget.md).
- Target motion: pluggable provider families — linear astrometry, catalog
  acceleration solutions, two-body orbits for resolved binaries and
  barycenters (validated against the published Alpha Cen AB and Sirius AB
  solutions), and externally generated checksummed ephemerides (the only
  family that models planet endpoints).
- Observers: Earth center, terrestrial sites, Solar-System bodies from the
  pinned planetary ephemeris, spacecraft from checksummed tabular
  ephemerides or SPICE kernels, and programmatic observers for testing.

## Product boundary

SGLSETI ends at the generation and export of target products (ECSV, JSON,
CSV, VOTable, DS9 regions, and a provenance manifest). It does **not**
query archives, ingest observations, track historical search coverage,
manage candidates, or schedule telescopes. Those belong to external systems
that consume SGLSETI output.

## Status

v1.1, survey-ready: the full survey-driven roadmap
(`notes/improvements.md`) is implemented and verified — 480+ offline
tests, including frozen fixtures for two published SGL searches and
microarcsecond-level cross-validation against JPL Horizons. Identities
(calculation IDs, content hashes) are at their frozen greenfield baseline
for the first archival consumers. Remaining open items are deliberately
gated or demand-driven (see the note).

## Documentation

- [Quick start](https://github.com/jgrizzled/sglseti/blob/main/docs/quickstart.md) — all workflows, CLI and Python
- [Target registry](https://github.com/jgrizzled/sglseti/blob/main/docs/registry.md) — schema, provider families,
  provenance and covariance blocks
- [Conventions and product reference](https://github.com/jgrizzled/sglseti/blob/main/docs/conventions.md) — frames, time
  scales, role epochs, every output column
- [Accuracy budget](https://github.com/jgrizzled/sglseti/blob/main/docs/accuracy_budget.md) — measured floors and declared
  approximations by model, observer type, epoch span, and provider
- [Resources](https://github.com/jgrizzled/sglseti/blob/main/docs/resources.md) — pinned ephemeris kernels and IERS, offline
- [Limitations](https://github.com/jgrizzled/sglseti/blob/main/docs/limitations.md) — model validity and boundaries
- [Benchmarks](https://github.com/jgrizzled/sglseti/blob/main/docs/benchmarks.md) — archive-scale performance measurements
- [Science specification](https://github.com/jgrizzled/sglseti/blob/main/docs/science/geometry_models.md) and
  [ADRs](https://github.com/jgrizzled/sglseti/tree/main/docs/adr) — the reviewed model contracts

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
write_products(result, "build/archive-targets", generated_utc="2026-08-18T00:00:00+00:00")
```

Every output row keeps its caller-supplied `epoch_id` join key, its
coordinate frame/origin/epoch semantics, model identity, target- and
observer-provider identity, resource checksums, and validity status; a
`manifest.json` separates the deterministic science identity from run
circumstance. A taste of the survey-facing API:

```python
from astropy.time import Time
from sglseti import (
    AstropyEphemeris,
    Observer,
    RelayRange,
    Role,
    Tusay2022Eq57V1,
    adaptive_locus,
    covered_z_intervals,
)

locus = adaptive_locus(  # polyline within 0.5" of the
    target=registry["barnard"],  # continuous locus, guaranteed
    role=Role.RX,
    observation_time=Time("2015-09-05T07:41:00", scale="utc"),
    observer=Observer.earth_center(),
    relay_range=RelayRange(550.0, 2500.0),
    tolerance_arcsec=0.5,
    ephemeris=AstropyEphemeris(),
    model=Tusay2022Eq57V1(),
)
# ...then refine your instrument footprint into covered z intervals with
# covered_z_intervals(contains=your_footprint_test, ...)
```

See the [quick start](https://github.com/jgrizzled/sglseti/blob/main/docs/quickstart.md) for observation intervals,
uncertainty propagation, crossings, and chunked archive-scale execution.

## Ephemeris resources

Calculations never touch the network. Astropy's built-in analytic ephemeris
works out of the box (its relay-pointing floor is ≤ 0.02 mas — see the
accuracy budget); citable products should pin the canonical kernel
**JPL DE440s** (ADR-0002), fetched once with the only network-using command:

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
identified in provenance). The `jpl_file` ephemeris adapter needs the
`jpl` extra (`uv sync --extra jpl` or `pip install 'sglseti[jpl]'`); the
SPICE spacecraft observer needs the `spice` extra (`spiceypy`).

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
