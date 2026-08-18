# Conventions and product reference

Authoritative conventions for every sglseti output. The science model
itself is specified in [science/geometry_models.md](science/geometry_models.md).

## Frames, origins, corrections

| Product | Frame / origin | Correction |
|---|---|---|
| `icrs_ra_deg`, `icrs_dec_deg` | ICRS direction of the relay from the stated observer (barycentric vectors, observer origin) | geometric — no aberration, light deflection, or refraction |
| `cirs_ra_deg`, `cirs_dec_deg` | CIRS; topocentric for site observers, geocentric for Earth center | apparent (astropy frame machinery), approximate for finite-distance objects |
| `altaz_alt_deg`, `altaz_az_deg` | AltAz at the site | apparent, refraction disabled |
| visibility altitudes / Moon separation | AltAz / angular separation of geometric directions | geometric-approximate; for constraints, not pointing |

Observer origin is explicit per row (`observer_id`); Earth-center and
terrestrial-site observers are never mixed silently.

## Time scales and role epochs

- `observation_time_utc`: ISO-8601 UTC (the requested epoch `t_o`).
- `*_tdb_jd`: TDB Julian dates used for computation.
- `catalog_direction_epoch_tdb_jd`: the **SSB light-arrival epoch** `u` used
  for catalog propagation (`catalog_epoch_semantics =
  ssb_light_arrival_time`). Under `tusay2022_eq5_7_v1`:
  `antipode u = t_o`, `rx u = t_o − 2z/c`, `tx u = t_o + 2d/c`.
- `target_event_epoch_tdb_jd_approx` + `target_event_kind`: the approximate
  *physical* emission/arrival/apparent event — a diagnostic, never a
  propagation input. Do not confuse it with the catalog epoch; the
  difference is one target light time (`target_light_time_days`).
- Registry reference epochs keep their declared scale (Gaia: TCB).

## Sample table columns (`samples.ecsv` / `.csv` / JSON `samples`)

| Group | Columns |
|---|---|
| identity | `corridor_id`, `calculation_id`, `epoch_id`, `target_id`, `role`, `sample_id` |
| time | `observation_time_utc`, `observation_time_tdb_jd`, `catalog_direction_epoch_tdb_jd`, `relay_event_epoch_tdb_jd_approx`, `solar_lens_epoch_tdb_jd_approx`, `target_event_epoch_tdb_jd_approx`, `target_event_kind` |
| light times [d] | `target_light_time_days`, `sun_relay_light_time_days`, `observer_relay_light_time_days_approx` |
| range | `z_au` (representative reciprocal-midpoint distance), `q_per_au` = 1/z |
| geometry | `icrs_ra_deg`, `icrs_dec_deg`, `observer_id` |
| model | `model_id`, `model_version`; approximation flags `rho_equals_z_assumed`, `constant_target_distance_assumed`, `linear_stellar_motion_assumed`, `solar_motion_neglected`; `catalog_epoch_semantics` |
| provenance | `target_source_hash`, `ephemeris_id` (content checksum for file-backed kernels) |
| quality | `validity` (valid/degraded/invalid), `uncertainty_method` (assumed/not_propagated), `warnings` (`;`-joined machine-readable codes) |
| optional | `cirs_*`, `altaz_*`, `rate_ra_cosdec_arcsec_per_hr`, `rate_dec_arcsec_per_hr` (central finite difference, 60 s step) |

Invalid rows carry NaN (ECSV/CSV) or `null` (JSON) coordinates plus a
reason code — never a fabricated position.

## Corridor, visibility, and pointing tables

- `corridors.ecsv`: one row per target/role/epoch — `corridor_id`, range
  bounds, `sample_count`, `sample_ids` (`;`-joined, ordered near→far),
  `uncertainty_method`, `assumed_half_width_arcsec`,
  `max_motion_padding_arcsec` (reserved; empty in v1 — motion padding is
  reported per pointing), aggregated warnings. The ordered samples
  themselves are the polyline: position ↔ relay range via each sample's
  `z_au`.
- `visibility.ecsv`: per role/epoch — `altitude_deg`, `azimuth_deg`,
  `sun_altitude_deg`, `moon_separation_deg`, `constraints_passed`,
  `failed_constraints`. Thresholds are inclusive.
- `pointings.ecsv`: candidate zones with the conservative radius and its
  labeled components: `radius_arcsec = track_extent_arcsec +
  assumed_half_width_arcsec + motion_padding_arcsec`
  (`propagated_half_width_arcsec` is always empty in v1). Windows
  (`window_start_utc`/`window_stop_utc`) are grid-sampled;
  `representative_time_utc` is the window's middle grid point.

## Warning codes

`below_solar_focal_minimum`, `long_propagation_span`,
`missing_radial_velocity`, `relay_beyond_model_bound` (invalid),
`ephemeris_out_of_coverage:*` (invalid), `uncertainty_not_propagated`,
`invalid_sample_count:N`, `degraded_sample_count:N`,
`no_visible_window:target/role`, `group_exceeds_usable_fov`, plus
`astropy:*` propagation messages.

## Uncertainty

An `assumed` half-width is a configured search pad, **not** catalog
covariance, an error bar, or a confidence region. Without one, outputs are
labeled `uncertainty_method = not_propagated` and warned; narrow-field
scientific use then requires an independently justified envelope. DS9
regions (which draw a width) refuse to generate without an explicit assumed
half-width.
