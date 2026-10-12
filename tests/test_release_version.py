"""Keep distribution, CLI, and report version declarations aligned."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

from click.testing import CliRunner
from ruamel.yaml import YAML

from eoap_validator.cli import main
from eoap_validator.models import Report as WireReport
from eoap_validator.report import Report


def test_release_version_consistency() -> None:
    installed = version("eoap-validator")
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().endswith(installed)
    report = Report(source="file:///example.cwl")
    assert report.validator_version == installed
    assert report.to_dict()["validator_version"] == installed
    assert WireReport.model_fields["validator_version"].default == installed
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "report.yaml"
    schema = YAML(typ="safe").load(schema_path.read_text())
    assert (
        schema["$defs"]["ReportData"]["properties"]["validator_version"]["default"]
        == installed
    )
