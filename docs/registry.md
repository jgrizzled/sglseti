# Target registry schema

The target registry is a reviewable YAML file with a single schema
(`schema_version: 2`). Loading is strict: unknown keys, non-finite values,
missing frames/epochs/provenance, and provider/endpoint mismatches are
errors, never silently dropped or defaulted.

> Greenfield note (2026-08-18): earlier drafts carried a v1 schema and a
> migration path. Before first operational use the package standardized on
> this single schema; there are no v1 registries to migrate.

## Layout

Each target's `state` block names the target-state provider family and
carries the adopted solution:

```yaml
schema_version: 2
targets:
  barnard:
    display_name: "Barnard's Star"
    endpoint_kind: star            # star | component | barycenter | planet
    priority: 1.0
    tags: [tier1]
    flags: []
    notes: "..."
    identifiers:                   # optional, immutable catalog/literature ids
      - catalog: "Gaia DR3"
        id: "4472832130942575872"
        version: "DR3"
    quality: "..."                 # optional free-form quality indicator
    model_rationale: "..."         # optional model-selection rationale
    state:
      provider: linear_astrometry_v1
      astrometry:
        frame: icrs
        ra_deg: 269.45207695861876
        dec_deg: 4.693364966576667
        parallax_mas: 546.9759     # exactly one of parallax_mas / distance_pc
        pm_ra_cosdec_mas_per_yr: -801.551
        pm_dec_mas_per_yr: 10362.394
        radial_velocity_km_s: -110.11
        reference_epoch_jyear: 2000.0
        reference_epoch_scale: tcb # tcb | tdb | tt | tai | utc
        source: "immutable catalog release statement"
      provenance:                  # optional per-value provenance
        parallax_mas:
          source: "Gaia DR3 ..."
          uncertainty: 0.03        # 1-sigma, requires an explicit unit
          unit: mas
      covariance:                  # optional, full matrix only
        parameters: [ra, dec, parallax, pm_ra_cosdec, pm_dec]  # declared ordering
        units: [mas, mas, mas, mas/yr, mas/yr]
        kind: correlation          # covariance | correlation
        matrix: [[1.0, ...], ...]  # square, symmetric
      acceleration: { ... }        # required iff provider: acceleration_astrometry_v1
      orbit: { ... }               # required iff provider: two_body_orbit_v1
      sampled_state: { ... }       # required iff provider: sampled_state_v1
```

## Provider families

- **`linear_astrometry_v1`** — one linear six-parameter state propagated
  rigidly (astropy `apply_space_motion`). Endpoint kinds: `star`,
  `component`, `barycenter`. The flags `unresolved_binary` and
  `accelerating_system` are validation errors here: the linear family
  cannot model that motion.
- **`acceleration_astrometry_v1`** — linear astrometry plus catalog
  quadratic terms about the same reference epoch (e.g. Hipparcos-Gaia
  long-baseline accelerations). The `acceleration` block requires
  `accel_ra_cosdec_mas_per_yr2`, `accel_dec_mas_per_yr2`, and `source`.
  Accepts the `accelerating_system` / `unresolved_binary` flags.
- **`two_body_orbit_v1`** — resolved components and system barycenters.
  `state.astrometry` describes the system **barycenter**; the `orbit`
  block is the published relative solution (Campbell elements of the
  secondary about the primary, position angles east of north, periastron
  epoch in observation-date years): `period_yr`,
  `periastron_epoch_jyear`, `eccentricity`, `semimajor_axis_arcsec`,
  `inclination_deg`, `ascending_node_deg`, `arg_periastron_deg`,
  `mass_fraction_secondary` (`M_sec / (M_pri + M_sec)`), `component`
  (`primary` | `secondary` | `barycenter`), and `source`. A `barycenter`
  endpoint requires `component: barycenter` and vice versa. Declared
  approximations: tangential offset only (orbital line-of-sight
  displacement and orbital radial velocity neglected) and a fixed angular
  semimajor axis.
- **`sampled_state_v1`** — an externally generated, CHECKSUMMED
  ephemeris of the endpoint itself. `state.astrometry` remains the
  approximate reference solution (checked for gross consistency at
  load); the adopted solution is an ECSV table of barycentric ICRS
  positions (`epoch_tdb_jd`, `x_au`/`y_au`/`z_au`, optional
  `v*_au_per_day` columns enabling cubic-Hermite interpolation). The
  `sampled_state` block requires `path`, `checksum_sha256` (mandatory —
  identities use the checksum, never the path), `epoch_semantics`
  (`ssb_light_arrival_time` | `physical_event_time`; the v1 geometry
  model refuses the latter explicitly), and `source`. Epochs outside the
  tabulated span become invalid status rows. This is the only family
  that models `planet` endpoints. Parameter-based uncertainty sampling
  does not apply to sampled targets — express uncertainty in the
  ephemeris itself.

`endpoint_kind: other` is recognized by the schema but rejected at
validation until a provider family models it (improvements note §2.1);
`planet` is accepted only with `sampled_state_v1`.

## Identity

`source_hash` is a SHA-256 over the normalized registry content (the
plain-dict form of `TargetRegistry.to_normalized_dict()`, itself a valid
registry file), so it is stable across formatting, key order, and comment
changes. Per the package-wide canonical rules, target identities used in
calculation IDs (`target_source_hash`) omit default-valued fields — so
future schema fields can never move existing identities — and never
contain filesystem paths: file-backed resources contribute their pinned
content checksums.
