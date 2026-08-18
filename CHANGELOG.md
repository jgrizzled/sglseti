# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Domain models and input validation (Phase 2): frozen dataclasses and enums
  for the scientific boundary (`sglseti.models`), strict curated target
  registry loading with normalized source hash and missing-radial-velocity
  policy (`sglseti.targets`), request schema v1 with exactly one time mode
  and strict-UTC ECSV/CSV epoch tables (`sglseti.config`), `sglseti validate
  targets|request` CLI commands, lazy top-level re-exports, and the
  historical/commensal example inputs.
- Package scaffold: installable `sglseti` package with `pyproject.toml`,
  `sglseti` console script, domain-error CLI boundary, typed-package marker,
  unit/integration/regression test layout, import-hygiene test (no sqlite3,
  no network, no file access at import), and CI configuration.
