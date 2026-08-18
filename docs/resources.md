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

Offline runs use astropy's bundled IERS-B tables; sglseti scopes
auto-download off during every calculation (no global configuration is
touched). The effect of stale tables on sglseti products is at the
milliarcsecond level — far below the model's ~0.1″ floor. To refresh
predictions explicitly:

```bash
sglseti fetch iers
```

## Offline verification

The reproducibility gate is CI-tested
(`tests/integration/test_release_gates.py`): with all network access
blocked at the audit-hook level, a pinned-kernel run repeated from a
different working directory produces identical `calculation_id`s,
byte-identical science products, and the same manifest science hash. The
committed test kernel is a DE440s excerpt whose full derivation is in
`tests/data/kernels/README.md`.
