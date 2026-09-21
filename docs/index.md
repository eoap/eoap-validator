# EOAP Validator

Inspect an EO Application Package before generating publication artifacts or
registering it with a platform. EOAP Validator is a standalone Python library
and CLI that validates CWL, evaluates EOAP package rules, and optionally checks
Transpiler-Mate software metadata. It does not execute workflows or pull container
images.

See the [README](https://github.com/eoap/eoap-validator#readme) for installation
instructions and CLI and library examples.

- [Use the CLI](how-to/cli.md) to validate a workflow and save a report.
- [Use validation in CI](how-to/ci.md) to produce reports in your pipeline.
- [Profiles and reporting](reference/profiles.md) describes the checks, report
  contract, and exit codes.
- [Architecture and boundaries](explanation/architecture.md) explains how the
  validator works and the limits of its assessment.
