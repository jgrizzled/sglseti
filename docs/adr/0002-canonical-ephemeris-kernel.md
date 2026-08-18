# ADR-0002: Canonical ephemeris kernel and explicit network access

Date: 2026-08-17
Status: Accepted

## Context

The PRD (open decision 3) requires choosing the canonical file-backed JPL
ephemeris fixture for release tests, and FR-015/NFR-008 forbid implicit
network access during calculation while permitting "a separate, explicit
resource-acquisition step." Phase 4 shipped a `jpl_file` adapter with no
real-kernel regression coverage.

Candidates surveyed (JPL SSD / NAIF, verified 2026-08-17): DE440s
(1849–2150, ~32 MB, current-standard solution, short span), DE440
(1549–2650, ~114 MB), DE441 (deep time, ~2.6 GB), DE430/DE432 (superseded),
DE421 (old solution, future coverage ends 2053).

## Decision

1. **Canonical kernel: JPL DE440s**, pinned by content checksum
   `sha256:c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2`
   (NAIF download, 2026-08-17; 32,726,016 bytes; coverage 1849-12-26 to
   2150-01-22). It is the current JPL standard solution and covers the full
   realistic archival window plus a century of planning.
2. **Committed CI fixture: a DE440s excerpt** (`jplephem excerpt`, segments
   SSB→EMB, SSB→Sun, EMB→Earth, span 2010–2035, 1.16 MB) at
   `tests/data/kernels/de440s_excerpt_2010-2035.bsp`, with full derivation
   provenance in the adjacent README and its own pinned checksum. Default
   tests exercise the real `jpl_file` path offline. An excerpt is a derived
   resource: manifests record the checksum of whatever file actually backed
   a run.
3. **Network access happens only in `sglseti fetch`** (module
   `sglseti.resources`) — never during calculation. `fetch ephemeris`
   downloads a registry kernel (checksum-pinned) or an explicit `--url`
   (checksum always reported, verified when expected), atomically; `fetch
   iers` downloads the IERS-A table the same way — a pinned local file for
   a request's `iers` block, installed explicitly per calculation
   (sub-arcsecond nicety, never required; originally a cache refresh,
   changed 2026-08 when review finding 3 showed the cached table was never
   actually consumed).
4. Astropy's *named* remote ephemerides (`solar_system_ephemeris.set('jpl')`
   etc.) are **not** offered as an adapter: they download inside a
   calculation on first use and manage identity outside our manifest.
5. Horizons remains the optional, explicitly-marked external validation
   tier (plan §6.1) and is not part of default CI.

## Consequences

- Reproducible products cite `jpl_file:sha256:…` identities; builtin stays
  available for exploration (measured to agree with DE440s to ~1e-6 AU,
  ≈0.3 mas of locus direction at 550 AU, in 2021).
- The optional `jpl` dependency extra (`jplephem`) is required for
  file-backed kernels and included in the test dependency group.
- Epochs outside 2010–2035 in kernel-backed tests raise coverage errors by
  design; tests needing other epochs use builtin or regenerate the excerpt
  with a documented span change.
