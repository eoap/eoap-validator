from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

from eoap_validator import validate

if TYPE_CHECKING:
    from conftest import Writer


def with_output(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow, tool = document["$graph"]
    tool["outputs"] = {
        "result": {"type": "stdout", "label": "Result", "doc": "Echo output."}
    }
    tool["stdout"] = "result.txt"
    workflow["steps"]["echo"]["out"] = ["result"]
    workflow["outputs"] = {
        "result": {
            "type": "File",
            "outputSource": "echo/result",
            "label": "Result",
            "doc": "Echo output.",
        }
    }
    return workflow, tool


@pytest.mark.parametrize("field", ["label", "doc"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_entry_output_required(
    document: dict[str, Any], write: Writer, field: str, value: Any
) -> None:
    workflow, _ = with_output(document)
    if value is None:
        workflow["outputs"]["result"].pop(field)
    else:
        workflow["outputs"]["result"][field] = value
    report = validate(write(document))
    finding = next(
        f
        for f in report.findings
        if f.rule_id == f"EOAP.WORKFLOW.OUTPUT.{field.upper()}"
    )
    assert (
        getattr(finding.status, "value", finding.status),
        getattr(finding.severity, "value", finding.severity),
    ) == ("failed", "error")
    assert finding.location.path == "echo-application/outputs/result"
    assert finding.location.line is not None
    assert finding.reference is None
    assert report.exit_code() == 1


@pytest.mark.parametrize(
    "target,prefix",
    [
        ("steps", "EOAP.WORKFLOW.STEP"),
        ("inputs", "EOAP.CLT.INPUT"),
        ("outputs", "EOAP.CLT.OUTPUT"),
    ],
)
@pytest.mark.parametrize("field", ["label", "doc"])
def test_recommendations(
    document: dict[str, Any], write: Writer, target: str, prefix: str, field: str
) -> None:
    workflow, tool = with_output(document)
    item = (
        workflow["steps"]["echo"]
        if target == "steps"
        else next(iter(tool[target].values()))
    )
    item.pop(field)
    report = validate(write(document))
    finding = next(
        f for f in report.findings if f.rule_id == f"{prefix}.{field.upper()}"
    )
    assert (
        getattr(finding.status, "value", finding.status),
        getattr(finding.severity, "value", finding.severity),
    ) == ("needs-review", "warning")
    assert finding.location.line is not None
    assert finding.suggestion
    assert report.exit_code() == 0
    assert report.exit_code("warning") == 1


def test_documented_fields_pass(document: dict[str, Any], write: Writer) -> None:
    with_output(document)
    report = validate(write(document))
    findings = [
        f
        for f in report.findings
        if f.rule_id.startswith(("EOAP.WORKFLOW.", "EOAP.CLT."))
    ]
    expected_count = 8
    assert len(findings) == expected_count
    assert all(
        getattr(f.status, "value", f.status) == "passed"
        and getattr(f.severity, "value", f.severity) == "info"
        and f.suggestion is None
        for f in findings
    )
    assert report.profiles["eoap-package"] == "1.2"
    assert report.exit_code("warning") == 0


def test_nested_workflow_scope(document: dict[str, Any], write: Writer) -> None:
    workflow, _ = with_output(document)
    nested = deepcopy(workflow)
    nested["id"] = "nested"
    nested["outputs"]["result"].pop("doc")
    nested["steps"]["echo"]["label"] = " "
    workflow["requirements"] = {"SubworkflowFeatureRequirement": {}}
    workflow["steps"]["echo"]["run"] = "#nested"
    document["$graph"].append(nested)
    path = write(document)
    report = validate(path + "#echo-application")
    assert report.exit_code() == 0, report.to_dict()
    outputs = [f for f in report.findings if f.rule_id == "EOAP.WORKFLOW.OUTPUT.DOC"]
    assert (
        len(outputs) == 1
        and getattr(outputs[0].status, "value", outputs[0].status) == "passed"
    )
    assert any(
        f.rule_id == "EOAP.WORKFLOW.STEP.LABEL"
        and getattr(f.status, "value", f.status) == "needs-review"
        and f.location.path == "nested/steps/echo"
        for f in report.findings
    )
    report = validate(path + "#nested")
    assert report.exit_code() == 1
