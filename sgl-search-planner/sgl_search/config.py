from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a configuration file is missing a required or valid value."""


def _number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if value is None or isinstance(value, bool):
        raise ConfigError(f"Expected numeric value for '{key}'.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Expected numeric value for '{key}', got {value!r}.") from exc


def _integer(mapping: dict[str, Any], key: str) -> int:
    value = mapping.get(key)
    if value is None or isinstance(value, bool):
        raise ConfigError(f"Expected integer value for '{key}'.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Expected integer value for '{key}', got {value!r}.") from exc
    if parsed != float(value):
        raise ConfigError(f"Expected integer value for '{key}', got {value!r}.")
    return parsed


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Top level of {path} must be a mapping.")
    return data


@dataclass(frozen=True)
class TargetAstrometry:
    ra_deg: float
    dec_deg: float
    parallax_mas: float
    pm_ra_cosdec_mas_per_yr: float
    pm_dec_mas_per_yr: float
    radial_velocity_km_s: float
    reference_epoch_jyear: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
            "parallax_mas": self.parallax_mas,
            "pm_ra_cosdec_mas_per_yr": self.pm_ra_cosdec_mas_per_yr,
            "pm_dec_mas_per_yr": self.pm_dec_mas_per_yr,
            "radial_velocity_km_s": self.radial_velocity_km_s,
            "reference_epoch_jyear": self.reference_epoch_jyear,
            "source": self.source,
        }


@dataclass(frozen=True)
class Target:
    target_id: str
    display_name: str
    astrometry: TargetAstrometry
    priority: float
    tags: tuple[str, ...]
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "display_name": self.display_name,
            "priority": self.priority,
            "tags": list(self.tags),
            "notes": self.notes,
            "astrometry": self.astrometry.as_dict(),
        }


@dataclass(frozen=True)
class Site:
    name: str
    longitude_deg: float
    latitude_deg: float
    elevation_m: float


@dataclass(frozen=True)
class Night:
    start_utc: str
    end_utc: str
    grid_minutes: float


@dataclass(frozen=True)
class Instrument:
    telescope_id: str
    fov_shape: str
    fov_diameter_arcmin: float
    usable_fraction: float
    corridor_half_width_arcsec: float
    exposure_seconds: float
    overhead_seconds: float

    @property
    def usable_radius_arcsec(self) -> float:
        return self.fov_diameter_arcmin * 60.0 * 0.5 * self.usable_fraction


@dataclass(frozen=True)
class Constraints:
    min_altitude_deg: float
    max_sun_altitude_deg: float
    min_moon_separation_deg: float


@dataclass(frozen=True)
class Profile:
    profile_id: str
    signal_class: str
    band: str
    required_successful_visits: int
    min_visit_separation_days: float
    min_quality: float


@dataclass(frozen=True)
class TargetSelection:
    target_id: str
    roles: tuple[str, ...]
    min_au: float
    max_au: float
    partition_kind: str
    partition_step_arcsec: float | None
    partition_cells: int | None
    include_cells: tuple[str, ...]
    exclude_cells: tuple[str, ...]


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    geometry_model: str
    ephemeris: str
    iers_auto_download: bool
    site: Site
    night: Night
    instrument: Instrument
    constraints: Constraints
    profile: Profile
    selections: tuple[TargetSelection, ...]
    include_invisible: bool


def load_targets(path: str | Path) -> dict[str, Target]:
    data = load_yaml(path)
    if data.get("schema_version") != 1:
        raise ConfigError("targets.yaml must have schema_version: 1")
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise ConfigError("targets.yaml must contain a non-empty 'targets' mapping.")

    result: dict[str, Target] = {}
    for target_id, raw in raw_targets.items():
        if not isinstance(target_id, str) or not target_id:
            raise ConfigError("Every target key must be a non-empty string.")
        if not isinstance(raw, dict):
            raise ConfigError(f"Target '{target_id}' must be a mapping.")
        astro = raw.get("astrometry")
        if not isinstance(astro, dict):
            raise ConfigError(f"Target '{target_id}' is missing an astrometry mapping.")
        parsed_astro = TargetAstrometry(
            ra_deg=_number(astro, "ra_deg"),
            dec_deg=_number(astro, "dec_deg"),
            parallax_mas=_number(astro, "parallax_mas"),
            pm_ra_cosdec_mas_per_yr=_number(astro, "pm_ra_cosdec_mas_per_yr"),
            pm_dec_mas_per_yr=_number(astro, "pm_dec_mas_per_yr"),
            radial_velocity_km_s=_number(astro, "radial_velocity_km_s"),
            reference_epoch_jyear=_number(astro, "reference_epoch_jyear"),
            source=str(astro.get("source", "unspecified")),
        )
        if parsed_astro.parallax_mas <= 0:
            raise ConfigError(f"Target '{target_id}' must have positive parallax.")
        if not 0 <= parsed_astro.ra_deg < 360:
            raise ConfigError(f"Target '{target_id}' right ascension is outside [0, 360).")
        if not -90 <= parsed_astro.dec_deg <= 90:
            raise ConfigError(f"Target '{target_id}' declination is outside [-90, 90].")
        result[target_id] = Target(
            target_id=target_id,
            display_name=str(raw.get("display_name", target_id)),
            astrometry=parsed_astro,
            priority=float(raw.get("priority", 1.0)),
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
            notes=str(raw.get("notes", "")),
        )
    return result


def load_campaign(path: str | Path) -> Campaign:
    data = load_yaml(path)
    if data.get("schema_version") != 1:
        raise ConfigError("campaign.yaml must have schema_version: 1")

    site_raw = data.get("site")
    night_raw = data.get("night")
    instrument_raw = data.get("instrument")
    constraints_raw = data.get("constraints", {})
    profile_raw = data.get("profile")
    selection_raw = data.get("selection")
    for label, value in {
        "site": site_raw,
        "night": night_raw,
        "instrument": instrument_raw,
        "profile": profile_raw,
        "selection": selection_raw,
    }.items():
        if not isinstance(value, (dict, list)):
            raise ConfigError(f"campaign.yaml is missing a valid '{label}' section.")

    if not isinstance(site_raw, dict) or not isinstance(night_raw, dict):
        raise ConfigError("site and night must be mappings.")
    if not isinstance(instrument_raw, dict) or not isinstance(profile_raw, dict):
        raise ConfigError("instrument and profile must be mappings.")
    if not isinstance(constraints_raw, dict):
        raise ConfigError("constraints must be a mapping.")
    if not isinstance(selection_raw, list) or not selection_raw:
        raise ConfigError("selection must be a non-empty list.")

    fov_raw = instrument_raw.get("fov")
    if not isinstance(fov_raw, dict):
        raise ConfigError("instrument.fov must be a mapping.")

    selections: list[TargetSelection] = []
    for index, raw in enumerate(selection_raw):
        if not isinstance(raw, dict):
            raise ConfigError(f"selection[{index}] must be a mapping.")
        target_id = str(raw.get("target_id", ""))
        roles = tuple(str(role).lower() for role in raw.get("roles", []))
        valid_roles = {"receiver", "transmitter", "antipode"}
        if not target_id or not roles:
            raise ConfigError(f"selection[{index}] needs target_id and at least one role.")
        invalid = set(roles) - valid_roles
        if len(set(roles)) != len(roles):
            raise ConfigError(f"selection[{index}] contains duplicate roles.")
        if invalid:
            raise ConfigError(
                f"selection[{index}] has invalid roles {sorted(invalid)}; "
                f"choose from {sorted(valid_roles)}."
            )
        range_raw = raw.get("range_au")
        if not isinstance(range_raw, dict):
            raise ConfigError(f"selection[{index}].range_au must be a mapping.")
        min_au = _number(range_raw, "min")
        max_au = _number(range_raw, "max")
        if min_au <= 0 or max_au <= min_au:
            raise ConfigError(
                f"selection[{index}] requires 0 < range_au.min < range_au.max."
            )
        part_raw = raw.get("partition", {})
        if not isinstance(part_raw, dict):
            raise ConfigError(f"selection[{index}].partition must be a mapping.")
        kind = str(part_raw.get("kind", "inverse_range"))
        if kind != "inverse_range":
            raise ConfigError("Only partition.kind: inverse_range is implemented in v0.1.")
        step = part_raw.get("step_arcsec")
        cells = part_raw.get("cells")
        if step is None and cells is None:
            step = 15.0
        if step is not None and cells is not None:
            raise ConfigError("Specify either partition.step_arcsec or partition.cells, not both.")
        step_parsed = float(step) if step is not None else None
        cells_parsed = int(cells) if cells is not None else None
        if step_parsed is not None and step_parsed <= 0:
            raise ConfigError("partition.step_arcsec must be positive.")
        if cells_parsed is not None and cells_parsed <= 0:
            raise ConfigError("partition.cells must be positive.")

        selections.append(
            TargetSelection(
                target_id=target_id,
                roles=roles,
                min_au=min_au,
                max_au=max_au,
                partition_kind=kind,
                partition_step_arcsec=step_parsed,
                partition_cells=cells_parsed,
                include_cells=tuple(str(x) for x in raw.get("include_cells", [])),
                exclude_cells=tuple(str(x) for x in raw.get("exclude_cells", [])),
            )
        )

    campaign = Campaign(
        campaign_id=str(data.get("campaign_id", "")).strip(),
        geometry_model=str(data.get("geometry_model", "tusay2022")),
        ephemeris=str(data.get("ephemeris", "builtin")),
        iers_auto_download=bool(data.get("iers_auto_download", True)),
        site=Site(
            name=str(site_raw.get("name", "unnamed-site")),
            longitude_deg=_number(site_raw, "longitude_deg"),
            latitude_deg=_number(site_raw, "latitude_deg"),
            elevation_m=float(site_raw.get("elevation_m", 0.0)),
        ),
        night=Night(
            start_utc=str(night_raw.get("start_utc", "")),
            end_utc=str(night_raw.get("end_utc", "")),
            grid_minutes=float(night_raw.get("grid_minutes", 10.0)),
        ),
        instrument=Instrument(
            telescope_id=str(instrument_raw.get("telescope_id", "unknown")),
            fov_shape=str(fov_raw.get("shape", "circle")).lower(),
            fov_diameter_arcmin=_number(fov_raw, "diameter_arcmin"),
            usable_fraction=float(fov_raw.get("usable_fraction", 0.85)),
            corridor_half_width_arcsec=float(
                instrument_raw.get("corridor_half_width_arcsec", 20.0)
            ),
            exposure_seconds=float(instrument_raw.get("exposure_seconds", 300.0)),
            overhead_seconds=float(instrument_raw.get("overhead_seconds", 60.0)),
        ),
        constraints=Constraints(
            min_altitude_deg=float(constraints_raw.get("min_altitude_deg", 25.0)),
            max_sun_altitude_deg=float(constraints_raw.get("max_sun_altitude_deg", -12.0)),
            min_moon_separation_deg=float(
                constraints_raw.get("min_moon_separation_deg", 20.0)
            ),
        ),
        profile=Profile(
            profile_id=str(profile_raw.get("profile_id", "")).strip(),
            signal_class=str(profile_raw.get("signal_class", "unspecified")),
            band=str(profile_raw.get("band", "unspecified")),
            required_successful_visits=_integer(
                profile_raw, "required_successful_visits"
            ),
            min_visit_separation_days=float(
                profile_raw.get("min_visit_separation_days", 0.0)
            ),
            min_quality=float(profile_raw.get("min_quality", 0.0)),
        ),
        selections=tuple(selections),
        include_invisible=bool(data.get("output", {}).get("include_invisible", False)),
    )

    if not campaign.campaign_id:
        raise ConfigError("campaign_id must be non-empty.")
    if not campaign.profile.profile_id:
        raise ConfigError("profile.profile_id must be non-empty.")
    if campaign.geometry_model != "tusay2022":
        raise ConfigError("Only geometry_model: tusay2022 is implemented in v0.1.")
    if campaign.instrument.fov_shape != "circle":
        raise ConfigError("Only circular fields of view are implemented in v0.1.")
    if not (0 < campaign.instrument.usable_fraction <= 1):
        raise ConfigError("instrument.fov.usable_fraction must be in (0, 1].")
    if campaign.night.grid_minutes <= 0:
        raise ConfigError("night.grid_minutes must be positive.")
    if not -180 <= campaign.site.longitude_deg <= 180:
        raise ConfigError("site.longitude_deg must be in [-180, 180].")
    if not -90 <= campaign.site.latitude_deg <= 90:
        raise ConfigError("site.latitude_deg must be in [-90, 90].")
    if campaign.instrument.fov_diameter_arcmin <= 0:
        raise ConfigError("instrument.fov.diameter_arcmin must be positive.")
    if campaign.instrument.corridor_half_width_arcsec < 0:
        raise ConfigError("instrument.corridor_half_width_arcsec cannot be negative.")
    if campaign.instrument.exposure_seconds <= 0:
        raise ConfigError("instrument.exposure_seconds must be positive.")
    if campaign.instrument.overhead_seconds < 0:
        raise ConfigError("instrument.overhead_seconds cannot be negative.")
    if campaign.profile.required_successful_visits <= 0:
        raise ConfigError("profile.required_successful_visits must be positive.")
    if campaign.profile.min_visit_separation_days < 0:
        raise ConfigError("profile.min_visit_separation_days cannot be negative.")
    if not 0 <= campaign.profile.min_quality <= 1:
        raise ConfigError("profile.min_quality must be in [0, 1].")
    return campaign
