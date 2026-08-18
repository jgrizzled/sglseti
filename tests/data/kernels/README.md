# Ephemeris kernel test fixture

`de440s_excerpt_2010-2035.bsp` is a derived excerpt of the canonical sglseti
kernel **JPL DE440s** (ADR-0002), committed so the `jpl_file` adapter has a
real, offline, checksum-pinned regression path in default CI.

## Provenance

- Parent kernel: `de440s.bsp` from
  <https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp>
  (32,726,016 bytes), SHA-256
  `c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2`,
  downloaded 2026-08-17.
- Excerpt command (jplephem 2.24):

  ```bash
  python -m jplephem excerpt --targets 3,10,399 2010/1/1 2035/1/1 \
      de440s.bsp de440s_excerpt_2010-2035.bsp
  ```

- Resulting segments: SSB→Earth barycenter (3), SSB→Sun (10),
  EMB→Earth (399); coverage 2010-01-01 through 2035-01-01; 1,161,536 bytes.
- Excerpt SHA-256:
  `eca51b9422e7d3d0266b271757f575671dca585cf4cd744a87cbf4870d5f7530`
  (pinned in `tests/regression/test_jpl_kernel.py`).

An excerpt is a *derived* resource: its checksum intentionally differs from
DE440s proper, and a provenance manifest records whichever file actually
backed a run. Regenerating this fixture requires re-running the exact
command above against the checksummed parent kernel and updating the pinned
digest with a documented reason.
