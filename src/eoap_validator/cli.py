"""Standalone CLI. JSON output is never mixed with library diagnostics."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Literal

import click
from loguru import logger
from pydantic import ValidationError

from .engine import validate
from .report import PROFILES, Report, StagingConfig


@click.command()
@click.argument("source")
@click.option(
    "--profile",
    "profiles",
    multiple=True,
    type=click.Choice(PROFILES),
    help="Repeat to combine profiles. Default: eoap-package.",
)
@click.option(
    "--staging",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON applicability configuration; requires eoap-staging.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the full JSON report.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
)
@click.option(
    "--fail-on",
    type=click.Choice(["error", "warning"]),
    default="error",
    show_default=True,
)
@click.version_option("0.1.0")
def main(
    source: str,
    profiles: tuple[str, ...],
    staging: Path | None,
    output: Path | None,
    output_format: Literal["text", "json"],
    fail_on: Literal["error", "warning"],
) -> None:
    """Validate SOURCE, e.g. 'workflow.cwl#main', without executing it."""
    logger.disable("cwl_loader")
    try:
        config = (
            StagingConfig.model_validate_json(staging.read_text()) if staging else None
        )
        with redirect_stdout(sys.stderr):
            report = validate(
                source, profiles=profiles or ("eoap-package",), staging=config
            )
    except (ValueError, ValidationError, OSError) as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        raise click.exceptions.Exit(2) from exc
    code = report.exit_code(fail_on)
    payload = report.to_dict(fail_on)
    rendered = json.dumps(payload, indent=2)
    if output:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            click.echo(f"Cannot write report: {exc}", err=True)
            raise click.exceptions.Exit(2) from exc
    if output_format == "json":
        click.echo(rendered)
    else:
        render_text(report, code)
    raise click.exceptions.Exit(code)


def render_text(report: Report, code: int) -> None:
    for finding in report.findings:
        if getattr(finding.status, "value", finding.status) in {
            "passed",
            "not-applicable",
        }:
            continue
        loc = finding.location
        position = f":{loc.line}:{loc.column}" if loc.line is not None else ""
        severity = str(getattr(finding.severity, "value", finding.severity)).upper()
        status = getattr(finding.status, "value", finding.status)
        click.echo(
            f"{severity} [{status}] {finding.rule_id}\n"
            f"  {loc.uri}{position} {loc.path}\n  {finding.message}"
        )
        if finding.instance_path:
            click.echo("  Invocation: " + "/".join(finding.instance_path))
        if finding.suggestion:
            click.echo(f"  Fix: {finding.suggestion}")
    click.echo(f"Assessment: {report.counts}; exit status {code}.")
