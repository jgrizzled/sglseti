# Reviewed reference fixtures

Phase 0 artifacts: expected values for the `tusay2022_eq5_7_v1` geometry
model, derived **independently of the sgl-search-planner prototype**. The
Phase 4 geometry engine must reproduce them through its own code path within
each fixture's stated tolerance. Per the implementation plan, no fixture may
freeze unexplained prototype output as scientific truth.

Every fixture records: its derivation source, the model
(`tusay2022_eq5_7_v1`) and role-epoch convention it encodes, and a numeric
tolerance with rationale.

## Oracles

Two independent generators produced the frozen values:

- `generate_synthetic_fixtures.py` — pure-Python/stdlib first-principles
  flat-space light propagation. No astropy, no ERFA, no catalog-propagation
  conventions: the arrival-indexed catalog direction a(u) is *defined*
  physically by solving the emission-time equation. Feeds the synthetic
  fixtures.
- `tusay_eq57_reference.py` — a deliberately simple, no-abstraction astropy
  transcription of the published Tusay et al. (2022) equations 5–7, with its
  approximations documented in its docstring. Feeds the Alpha Centauri
  fixture.

Regenerating: run either script and diff against the frozen YAML. A change
in frozen values requires a documented reason (e.g., corrected constant),
never a silent refresh to match engine output.

## Fixtures

| File | Purpose | Value source |
|---|---|---|
| `solar_focal_distance.yaml` | z_min ≈ 547.76 AU from IAU constants | documented hand arithmetic |
| `role_epoch_offsets.yaml` | hand-checkable 2z/c and 2d/c light-time arithmetic | documented hand arithmetic |
| `static_synthetic.yaml` | zero-motion limit: all roles share one direction | `generate_synthetic_fixtures.py` |
| `constant_velocity_synthetic.yaml` | catalog-arrival vs physical-event equivalence; Rx/Tx distinction | `generate_synthetic_fixtures.py` |
| `double_retarded_negative.yaml` | NEGATIVE control: extra −d/c on Rx must be detected | `generate_synthetic_fixtures.py` |
| `barnard_scale_check.yaml` | high-proper-motion Rx/Tx offset scale and sign | documented hand arithmetic (derivation in file) |
| `alpha_cen_2021-11-06.yaml` | published-search epoch anchor (Tusay et al. 2022) | `tusay_eq57_reference.py` |

The hand-arithmetic fixtures embed their full derivations and are re-derived
from constants by `tests/unit/test_science_contract.py` on every run.

## Time convention in synthetic fixtures

Synthetic fixtures use one uniform time coordinate in days with
Julian-date-like numbering ("synthetic TDB"). They exercise epoch
*bookkeeping*, not time-scale conversion; time-scale tests belong to the
frame/time gate.
