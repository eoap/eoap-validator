from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

from eoap_validator import validate

if TYPE_CHECKING:
    from conftest import Writer

    from eoap_validator.models import Finding
    from eoap_validator.report import Report


def resource_failures(report: Report) -> list[Finding]:
    return [
        f
        for f in report.findings
        if f.rule_id.startswith("SCHEDULING.RESOURCE.")
        and getattr(f.status, "value", f.status) == "failed"
    ]


@pytest.mark.parametrize("field", ["coresMin", "coresMax", "ramMin", "ramMax", None])
def test_missing_resources(
    document: dict[str, Any], write: Writer, field: str | None
) -> None:
    requirements = document["$graph"][0]["requirements"]
    if field is None:
        del requirements["ResourceRequirement"]
    else:
        del requirements["ResourceRequirement"][field]
    report = validate(write(document))
    failed = resource_failures(report)
    assert len(failed) == (4 if field is None else 1)
    assert all(
        getattr(f.severity, "value", f.severity) == "error"
        and f.location.line is not None
        for f in failed
    )
    assert report.to_dict()["exit_code"] == 1


@pytest.mark.parametrize("owner", ["workflow", "step", "tool"])
def test_resource_inheritance(
    document: dict[str, Any], write: Writer, owner: str
) -> None:
    resources = document["$graph"][0].pop("requirements")
    target = {
        "workflow": document["$graph"][0],
        "step": document["$graph"][0]["steps"]["echo"],
        "tool": document["$graph"][1],
    }[owner]
    target.setdefault("requirements", {}).update(resources)
    assert validate(write(document)).exit_code() == 0


def test_local_requirement_replaces_inherited(
    document: dict[str, Any], write: Writer
) -> None:
    document["$graph"][1]["requirements"]["ResourceRequirement"] = {"coresMin": 1}
    expected_count = 3
    assert len(resource_failures(validate(write(document)))) == expected_count


def test_hints_do_not_satisfy_policy(document: dict[str, Any], write: Writer) -> None:
    document["$graph"][0]["hints"] = document["$graph"][0].pop("requirements")
    expected_count = 4
    assert len(resource_failures(validate(write(document)))) == expected_count


def test_reused_tool_has_distinct_resource_contexts(
    document: dict[str, Any], write: Writer
) -> None:
    resources = document["$graph"][0].pop("requirements")
    first = document["$graph"][0]["steps"]["echo"]
    second = deepcopy(first)
    first["requirements"] = resources
    document["$graph"][0]["steps"]["other"] = second
    report = validate(write(document))
    failed = resource_failures(report)
    expected_count = 4
    assert len(failed) == expected_count
    assert all(f.instance_path == ["echo-application", "other"] for f in failed)


@pytest.mark.parametrize("kind", ["Workflow", "CommandLineTool"])
@pytest.mark.parametrize("identifier", ["main", "#main"])
def test_main_id_rejected(
    document: dict[str, Any], write: Writer, kind: str, identifier: str
) -> None:
    process = next(p for p in document["$graph"] if p["class"] == kind)
    process["id"] = identifier
    if kind == "CommandLineTool":
        document["$graph"][0]["steps"]["echo"]["run"] = "#main"
    report = validate(write(document))
    finding = next(
        f
        for f in report.findings
        if f.rule_id == "SERVICE.PROCESS.ID"
        and getattr(f.status, "value", f.status) == "failed"
    )
    assert getattr(finding.severity, "value", finding.severity) == "error"
    assert finding.location.line is not None
    assert report.exit_code() == 1


@pytest.mark.parametrize("kind", ["Workflow", "CommandLineTool"])
def test_unreachable_main_rejected(
    document: dict[str, Any], write: Writer, kind: str
) -> None:
    process = deepcopy(next(p for p in document["$graph"] if p["class"] == kind))
    process["id"] = "main"
    document["$graph"].append(process)
    report = validate(write(document) + "#echo-application")
    assert any(
        f.rule_id == "SERVICE.PROCESS.ID"
        and getattr(f.status, "value", f.status) == "failed"
        for f in report.findings
    )


@pytest.mark.parametrize("profile", ["metadata", "eoap-staging"])
def test_policy_only_applies_to_package_profile(
    document: dict[str, Any], write: Writer, profile: str
) -> None:
    document["$graph"][0]["id"] = "main"
    del document["$graph"][0]["requirements"]
    report = validate(write(document), profiles=(profile,))
    assert not any(
        f.rule_id.startswith(("SERVICE.", "SCHEDULING.")) for f in report.findings
    )


def test_external_main_tool_rejected(document: dict[str, Any], write: Writer) -> None:
    tool = document["$graph"].pop()
    tool.update(cwlVersion="v1.2", id="main")
    write(tool, "tool.cwl")
    document["$graph"][0]["steps"]["echo"]["run"] = "tool.cwl"
    report = validate(write(document))
    finding = next(
        f
        for f in report.findings
        if f.rule_id == "SERVICE.PROCESS.ID"
        and getattr(f.status, "value", f.status) == "failed"
    )
    assert finding.location.uri.endswith("/tool.cwl")
    assert finding.location.line is not None


def test_resource_expressions_are_declarations(
    document: dict[str, Any], write: Writer
) -> None:
    document["$graph"][0]["requirements"]["InlineJavascriptRequirement"] = {}
    document["$graph"][0]["requirements"]["ResourceRequirement"] = {
        "coresMin": "$(1)",
        "coresMax": "$(2)",
        "ramMin": "$(256)",
        "ramMax": "$(512)",
    }
    assert validate(write(document)).exit_code() == 0
