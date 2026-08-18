# Ephemeris and Earth-orientation resources

Calculations never touch the network. `sglseti fetch` is the only networked
command; everything else consumes pinned local files identified by content
checksum ([ADR-0002](adr/0002-canonical-ephemeris-kernel.md)).

## Ephemeris options

| Adapter | Use | Identity |
|---|---|---|
| `astropy_builtin` (default) | exploration; agrees with DE440s to ~1e-6 AU (~0.3 mas of locus direction at 550 AU) | `astropy_builtin` |
| `jpl_file` | reproducible scientific products | `jpl_file:sha256:<content hash>` |

Canonical kernel: **JPL DE440s** (coverage 1849–2150, ~32 MB, SHA-256
`c1c7fee…49f2` pinned in the fetch registry). Acquire and pin it once:

```bash
sglseti fetch ephemeris de440s --output-dir resources/
```

then reference it in requests:

```yaml
ephemeris:
  adapter: jpl_file
  path: resources/de440s.bsp
```

The manifest and every sample row record the kernel's *content* checksum —
moving or renaming the file never changes any science ID. An optional
`checksum_sha256` in the spec makes a mismatched file a hard error. Other
kernels: `sglseti fetch ephemeris --url <kernel-url> [--expected-sha256 …]`.
Epochs outside a kernel's coverage produce explicit `invalid` rows (or fail
the batch under `--strict`), never silent values.

Requires the `jpl` extra (`jplephem`): `uv sync --extra jpl` or
`pip install 'sglseti[jpl]'`.

## Earth orientation (IERS)

Earth-orientation data affects only apparent (CIRS/AltAz) and
site-visibility products; geometric ICRS never depends on it. It follows
the same pinned-resource policy as kernels:

```bash
sglseti fetch iers --output-dir resources/
# prints the file's sha256 and coverage dates, plus the request snippet:
#   iers:
#     path: resources/finals2000A.all
#     checksum_sha256: sha256:…
```

A request's `iers` block installs that exact table for its calculations via
astropy's `earth_orientation_table` context — never cache discovery. The
table is republished weekly, so no checksum is pinned in the fetch registry;
pin the reported one in the request to freeze a run. Without an `iers`
block, astropy's bundled tables are used and identified by the
`astropy-iers-data` package version.

Either way the resolved identity (`iers_a:sha256:…` or
`iers_bundled:astropy-iers-data==…`) enters the calculation ID and manifest
whenever the request has apparent or site products — purely geometric IDs
never churn with Earth-orientation releases. Transforms at epochs outside
Earth-orientation coverage are labeled, never silent: captured astropy
warnings (and `iers_out_of_coverage` for a pinned table) degrade the
affected sample's validity, and visibility rows carry the same warnings.
The effect of stale tables is sub-arcsecond — real, but far below the
degree-scale margins of visibility constraints.

## Offline verification

The reproducibility gate is CI-tested
(`tests/integration/test_release_gates.py`): with all network access
blocked at the audit-hook level, a pinned-kernel run repeated from a
different working directory produces identical `calculation_id`s,
byte-identical science products, and the same manifest science hash. The
committed test kernel is a DE440s excerpt whose full derivation is in
`tests/data/kernels/README.md`.
