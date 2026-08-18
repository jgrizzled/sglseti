# Contributing to SGLSETI

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # creates .venv and installs the dev dependency group
uv run pytest
uv run ruff check .
uv run mypy
```

## Layout

- `sglseti/` — the package. §4.1: models → geometry/sampling →
  generate → observability → planning → export → CLI. Exporters never
  recalculate geometry; the CLI only parses arguments, calls public
  functions, writes results, and formats errors.
- `tests/unit/` — validation, sampling, IDs, pure vector math. No network.
- `tests/integration/` — Astropy frames/time/site/ephemeris and file
  formats. Local fixtures only.
- `tests/regression/` — reviewed historical/future coordinates against
  pinned resources. Expected values need a documented source, model
  version, and tolerance — never frozen, unexplained prototype output.
- `tests/data/` — fixture files, including reviewed reference values under
  `tests/data/reference/`.

## Ground rules

- **Stateless core.** No observation ledger, coverage database, SQLite,
  archive ingest, or candidate tracking anywhere under `sglseti/`.
- **Offline by default.** Importing `sglseti` and running the default test
  suite must not require network access or trigger implicit downloads
  (IERS, ephemeris kernels, name resolvers). The import-hygiene test
  enforces this at import time.
- **Explicit science.** Coordinate frames, origins, time scales, epochs,
  corrections, and approximations are explicit fields, never implied.
  Geometry models are named and versioned (e.g. `tusay2022_eq5_7_v1`).
- **Deterministic identity.** Stable IDs derive from normalized science
  inputs only — never output paths or generation timestamps.
- All user-facing errors derive from `sglseti.errors.SglsetiError`; the CLI
  reports them and exits with status 2.
