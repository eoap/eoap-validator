"""The checked-in JSON Schema describes actual CLI and library output."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from ruamel.yaml import YAML

from eoap_validator import models, validate
from eoap_validator.cli import main


@pytest.fixture
def schema_validator():
    schema = YAML(typ="safe").load(Path(__file__).parents[1] / "schemas/report.yaml")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize(
    "case", ["valid", "missing_metadata", "warning", "unreadable", "malformed"]
)
def test_reports_match_schema(document, write, tmp_path, schema_validator, case):
    if case == "missing_metadata":
        document.pop("s:author")
    elif case == "warning":
        document["s:description"] = " "
    path = write(document)
    if case == "unreadable":
        path = str(tmp_path / "absent.cwl")
    elif case == "malformed":
        Path(path).write_text("bad: [")
    report = validate(path, profiles=("eoap-package", "metadata"))
    for threshold in ("error", "warning"):
        payload = report.to_dict(threshold)
        schema_validator.validate(payload)
        generated = models.Report.model_validate(payload)
        assert generated.model_dump(mode="json", by_alias=True) == payload
        assert payload["exit_code"] == report.exit_code(threshold)
        assert sum(payload["counts"].values()) == len(payload["findings"])


def test_cli_report_and_aliases(document, write, tmp_path, schema_validator):
    document["s:description"] = " "
    output = tmp_path / "report.json"
    result = CliRunner().invoke(
        main,
        [
            write(document),
            "--profile",
            "metadata",
            "--fail-on",
            "warning",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    schema_validator.validate(payload)
    assert json.loads(output.read_text()) == payload
    assert payload["counts"]["needs-review"] > 0
    assert "needs_review" not in payload["counts"]
    assert payload["fail_on"] == "warning"


@pytest.mark.parametrize(
    "mutation", ["counts", "exit_code", "severity", "line", "extra"]
)
def test_schema_rejects_invalid_reports(document, write, schema_validator, mutation):
    payload = deepcopy(validate(write(document)).to_dict())
    if mutation == "counts":
        payload["counts"]["passed"] = -1
    elif mutation == "exit_code":
        payload["exit_code"] = 3
    elif mutation == "severity":
        payload["findings"][0]["severity"] = "fatal"
    elif mutation == "line":
        payload["findings"][0]["location"]["line"] = 0
    else:
        payload["unknown"] = True
    with pytest.raises(ValidationError):
        schema_validator.validate(payload)


def test_generated_collection_defaults_are_independent():
    first = models.ReportData(source="file:///a.cwl")
    second = models.ReportData(source="file:///b.cwl")
    first.dependencies.append("file:///tool.cwl")
    assert second.dependencies == []
