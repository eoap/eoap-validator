# Changelog

## [Unreleased]

### Added

- JSON Schema for the complete output report in `schemas/report.yaml` and
  generated Pydantic models produced by `task generate_ms_skeleton`.
- Schema validation tests for successful, failed, advisory and incomplete reports.

- Mandatory nonempty labels and documentation on entry-workflow outputs.
- Recommended labels and documentation on reachable workflow steps and
  CommandLineTool inputs/outputs. Updated the package profile to revision 1.1.

### Changed

- Reporting uses generated model fields with custom behavior in `report.py`.
  Library and CLI serialization share model validation and include `fail_on`.
- Corrected generation task input type to JSON Schema and output path to `src/`.

- Successful and inapplicable findings now use informational severity with no
  corrective suggestion. Successful package and staging messages describe the
  observed result rather than stating a requirement. Failure thresholds are unchanged.

- Renamed the `transpiler-mate` validation profile to `metadata` in the CLI,
  Python API and reports. The metadata requirements remain unchanged.

## [0.1.0] - 2026-09-21

### Added

- Independent CLI and library with `workflow.cwl#main` entrypoint selection.
- CWL validation, EOAP package and conditional staging profiles, and
  Transpiler-Mate metadata compatibility and quality checks.
- Structured findings, source locations where available, profile/tool versions,
  coverage counts, text/JSON reports and configurable CI failure thresholds.
- Regression coverage for legacy rules, relative references, inherited container
  contexts, invalid metadata and incomplete assessments.
