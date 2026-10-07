from copy import deepcopy

import pytest

from eoap_validator import validate


def resource_failures(report):
    return [
        f
        for f in report.findings
        if f.rule_id.startswith("SCHEDULING.RESOURCE.") and f.status == "failed"
    ]


@pytest.mark.parametrize("field", ["coresMin", "coresMax", "ramMin", "ramMax", None])
def test_missing_resources(document, write, field):
    requirements = document["$graph"][0]["requirements"]
    if field is None:
        del requirements["ResourceRequirement"]
    else:
        del requirements["ResourceRequirement"][field]
    report = validate(write(document))
    failed = resource_failures(report)
    assert len(failed) == (4 if field is None else 1)
    assert all(f.severity == "error" and f.location.line is not None for f in failed)
    assert report.to_dict()["exit_code"] == 1


@pytest.mark.parametrize("owner", ["workflow", "step", "tool"])
def test_resource_inheritance(document, write, owner):
    resources = document["$graph"][0].pop("requirements")
    target = {
        "workflow": document["$graph"][0],
        "step": document["$graph"][0]["steps"]["echo"],
        "tool": document["$graph"][1],
    }[owner]
    target.setdefault("requirements", {}).update(resources)
    assert validate(write(document)).exit_code() == 0


def test_local_requirement_replaces_inherited(document, write):
    document["$graph"][1]["requirements"]["ResourceRequirement"] = {"coresMin": 1}
    assert len(resource_failures(validate(write(document)))) == 3


def test_hints_do_not_satisfy_policy(document, write):
    document["$graph"][0]["hints"] = document["$graph"][0].pop("requirements")
    assert len(resource_failures(validate(write(document)))) == 4


def test_reused_tool_has_distinct_resource_contexts(document, write):
    resources = document["$graph"][0].pop("requirements")
    first = document["$graph"][0]["steps"]["echo"]
    second = deepcopy(first)
    first["requirements"] = resources
    document["$graph"][0]["steps"]["other"] = second
    report = validate(write(document))
    failed = resource_failures(report)
    assert len(failed) == 4
    assert all(f.instance_path == ["echo-application", "other"] for f in failed)


@pytest.mark.parametrize("kind", ["Workflow", "CommandLineTool"])
@pytest.mark.parametrize("identifier", ["main", "#main"])
def test_main_id_rejected(document, write, kind, identifier):
    process = next(p for p in document["$graph"] if p["class"] == kind)
    process["id"] = identifier
    if kind == "CommandLineTool":
        document["$graph"][0]["steps"]["echo"]["run"] = "#main"
    report = validate(write(document))
    finding = next(
        f
        for f in report.findings
        if f.rule_id == "SERVICE.PROCESS.ID" and f.status == "failed"
    )
    assert finding.severity == "error"
    assert finding.location.line is not None
    assert report.exit_code() == 1


@pytest.mark.parametrize("kind", ["Workflow", "CommandLineTool"])
def test_unreachable_main_rejected(document, write, kind):
    process = deepcopy(next(p for p in document["$graph"] if p["class"] == kind))
    process["id"] = "main"
    document["$graph"].append(process)
    report = validate(write(document) + "#echo-application")
    assert any(
        f.rule_id == "SERVICE.PROCESS.ID" and f.status == "failed"
        for f in report.findings
    )


@pytest.mark.parametrize("profile", ["metadata", "eoap-staging"])
def test_policy_only_applies_to_package_profile(document, write, profile):
    document["$graph"][0]["id"] = "main"
    del document["$graph"][0]["requirements"]
    report = validate(write(document), profiles=(profile,))
    assert not any(
        f.rule_id.startswith(("SERVICE.", "SCHEDULING.")) for f in report.findings
    )


def test_external_main_tool_rejected(document, write):
    tool = document["$graph"].pop()
    tool.update(cwlVersion="v1.2", id="main")
    write(tool, "tool.cwl")
    document["$graph"][0]["steps"]["echo"]["run"] = "tool.cwl"
    report = validate(write(document))
    finding = next(
        f
        for f in report.findings
        if f.rule_id == "SERVICE.PROCESS.ID" and f.status == "failed"
    )
    assert finding.location.uri.endswith("/tool.cwl")
    assert finding.location.line is not None


def test_resource_expressions_are_declarations(document, write):
    document["$graph"][0]["requirements"]["InlineJavascriptRequirement"] = {}
    document["$graph"][0]["requirements"]["ResourceRequirement"] = {
        "coresMin": "$(1)",
        "coresMax": "$(2)",
        "ramMin": "$(256)",
        "ramMax": "$(512)",
    }
    assert validate(write(document)).exit_code() == 0
