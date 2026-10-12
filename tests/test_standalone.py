from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner
from ruamel.yaml import YAML

from eoap_validator import validate
from eoap_validator.cli import main
from eoap_validator.source import Source
from eoap_validator.standalone import standalone_checks

if TYPE_CHECKING:
    from conftest import Writer

OPERATIONAL_FAILURE = 2
SCHEMA = "EOAP.SCHEMA.LOCAL_IMPORT"
PROCESS = "EOAP.PROCESS.EXTERNAL_REFERENCE"
LOCAL = [
    "eoap-types.yaml",
    "./types.yaml",
    "../types.yaml",
    "/opt/types.yaml",
    "file:///tmp/types.yaml",
]
REMOTE = [
    "https://raw.githubusercontent.com/eoap/schemas/main/geojson.yaml",
    "https://raw.githubusercontent.com/eoap/schemas/main/string_format.yaml",
    "http://example.org/types.yaml",
]


def checks(data: Any) -> list[Any]:
    # Round trip preserves the source marks used in real reports.
    from io import StringIO

    stream = StringIO()
    YAML().dump(data, stream)
    return standalone_checks(
        Source("file:///tmp/application.cwl", YAML().load(stream.getvalue()))
    )


@pytest.mark.parametrize("target", LOCAL + REMOTE)
@pytest.mark.parametrize("form", ["mapping", "list"])
@pytest.mark.parametrize("owner", ["workflow", "tool", "step"])
@pytest.mark.parametrize("collection", ["requirements", "hints"])
def test_schema_import_policy(
    document: dict[str, Any], target: str, form: str, owner: str, collection: str
) -> None:
    workflow, tool = document["$graph"]
    node = {"workflow": workflow, "tool": tool, "step": workflow["steps"]["echo"]}[
        owner
    ]
    body = {"types": [{"$import": target}]}
    node[collection] = (
        {"SchemaDefRequirement": body}
        if form == "mapping"
        else [{"class": "SchemaDefRequirement", **body}]
    )
    findings = checks(document)
    if target in REMOTE:
        assert not findings
    else:
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == SCHEMA
        assert finding.status == "failed" and finding.severity == "error"
        assert target in finding.message
        assert "single-file" in finding.message
        assert "SchemaDefRequirement.types" in finding.suggestion
        assert finding.location.path.endswith("/$import")
        assert finding.location.line is not None and finding.location.column is not None


@pytest.mark.parametrize(
    "target", LOCAL + REMOTE + ["tool.cwl#echo", "//example.org/tool.cwl"]
)
@pytest.mark.parametrize("form", ["mapping", "list"])
@pytest.mark.parametrize("wrapper", [False, True])
def test_external_process_policy(target: str, form: str, wrapper: bool) -> None:
    step = {"id": "execute", "run": {"$import": target} if wrapper else target}
    data = {
        "class": "Workflow",
        "steps": {"execute": step} if form == "mapping" else [step],
    }
    findings = checks(data)
    assert len(findings) == 1
    assert findings[0].rule_id == PROCESS
    assert target in findings[0].message
    assert "$graph" in findings[0].suggestion and "#id" in findings[0].suggestion
    assert findings[0].location.path.endswith("/run/$import" if wrapper else "/run")


@pytest.mark.parametrize(
    "run", ["#echo", {"class": "CommandLineTool", "inputs": [], "outputs": []}]
)
def test_internal_processes_allowed(run: Any) -> None:
    assert not checks({"class": "Workflow", "steps": {"echo": {"run": run}}})


def test_nested_workflow_and_unreachable_declarations(document: dict[str, Any]) -> None:
    child = {"class": "Workflow", "steps": [{"run": "nested-tool.cwl"}]}
    document["$graph"][0]["steps"]["echo"]["run"] = child
    document["$graph"].append(
        {"class": "Workflow", "steps": {"unused": {"run": "unused.cwl"}}}
    )
    assert [f.rule_id for f in checks(document)] == [PROCESS, PROCESS]


def test_nested_schema_and_remote_base() -> None:
    data = {
        "$base": "https://example.org/",
        "requirements": {
            "SchemaDefRequirement": {
                "types": [
                    {"$import": "relative.yaml"},
                    {
                        "name": "Record",
                        "type": "record",
                        "fields": [
                            {"name": "nested", "type": {"$import": "nested.yaml"}}
                        ],
                    },
                    {"$import": REMOTE[0]},
                ]
            }
        },
    }
    assert [f.rule_id for f in checks(data)] == [SCHEMA, SCHEMA]


def test_unrelated_data_and_inline_schema_allowed() -> None:
    data = {
        "inputs": {"file": {"default": {"class": "File", "location": "input.dat"}}},
        "doc": {"$include": "README.md"},
        "extension": {"run": "script.sh", "$import": "other.yaml"},
        "requirements": {
            "SchemaDefRequirement": {
                "types": [{"name": "Record", "type": "record", "fields": []}]
            }
        },
    }
    assert not checks(data)


@pytest.mark.parametrize("profile", ["metadata", "eoap-staging"])
def test_profile_scope(document: dict[str, Any], write: Writer, profile: str) -> None:
    document["$graph"][0]["steps"]["echo"]["run"] = "missing.cwl"
    report = validate(write(document), profiles=(profile,))
    assert not any(f.rule_id in {SCHEMA, PROCESS} for f in report.findings)


@pytest.mark.parametrize("kind", ["schema", "process"])
def test_missing_dependency_keeps_actionable_finding(
    document: dict[str, Any], write: Writer, kind: str
) -> None:
    workflow = document["$graph"][0]
    if kind == "schema":
        workflow["requirements"]["SchemaDefRequirement"] = {
            "types": [{"$import": "missing.yaml"}]
        }
    else:
        workflow["steps"]["echo"]["run"] = "missing.cwl"
    path = write(document)
    report = validate(path)
    assert report.exit_code() == OPERATIONAL_FAILURE
    payload = report.to_dict()
    policy = [f for f in payload["findings"] if f["rule_id"] in {SCHEMA, PROCESS}]
    assert len(policy) == 1 and policy[0]["suggestion"]
    assert policy[0]["location"]["uri"].endswith("workflow.cwl")
    result = CliRunner().invoke(main, [path, "--format", "json"])
    assert result.exit_code == OPERATIONAL_FAILURE
    assert policy[0]["rule_id"] in result.output


def test_existing_local_schema_fails_policy(
    document: dict[str, Any], write: Writer
) -> None:
    write({"name": "Custom", "type": "record", "fields": []}, "types.yaml")
    document["$graph"][0]["requirements"]["SchemaDefRequirement"] = {
        "types": [{"$import": "types.yaml"}]
    }
    report = validate(write(document))
    assert report.exit_code() == 1, report.to_dict()
    assert any(f.rule_id == SCHEMA for f in report.findings)


def test_inline_tool_passes_full_validation(
    document: dict[str, Any], write: Writer
) -> None:
    tool = deepcopy(document["$graph"].pop())
    document["$graph"][0]["steps"]["echo"]["run"] = tool
    report = validate(write(document))
    assert report.exit_code() == 0, report.to_dict()
    assert report.profiles["eoap-package"] == "1.3"


def test_exact_import_location() -> None:
    content = """class: Workflow
requirements:
  SchemaDefRequirement:
    types:
      - $import: eoap-types.yaml
"""
    finding = standalone_checks(
        Source("file:///tmp/example.cwl", YAML().load(content))
    )[0]
    assert finding.location.model_dump() == {
        "uri": "file:///tmp/example.cwl",
        "path": "/requirements/SchemaDefRequirement/types/0/$import",
        "line": 5,
        "column": 9,
    }


def test_mixed_schemas_report_only_local_imports() -> None:
    data = {
        "requirements": [
            {
                "class": "SchemaDefRequirement",
                "types": [
                    {"$import": REMOTE[0]},
                    {"$import": REMOTE[1]},
                    {"$import": "eoap-types.yaml"},
                ],
            }
        ]
    }
    findings = checks(data)
    assert len(findings) == 1
    assert "eoap-types.yaml" in findings[0].message


@pytest.mark.parametrize("value", [None, 123, [], {}, [None], {"invalid": None}])
def test_malformed_steps_do_not_crash_source_checks(value: Any) -> None:
    assert not checks({"class": "Workflow", "steps": value})


def test_inline_schema_passes_full_validation(
    document: dict[str, Any], write: Writer
) -> None:
    document["$graph"][0]["requirements"]["SchemaDefRequirement"] = {
        "types": [{"name": "Custom", "type": "record", "fields": []}]
    }
    report = validate(write(document))
    assert report.exit_code() == 0, report.to_dict()


def test_external_subworkflow_fails_policy(
    document: dict[str, Any], write: Writer
) -> None:
    child = deepcopy(document["$graph"][0])
    child.update(id="child", cwlVersion="v1.2")
    child["steps"]["echo"]["run"] = document["$graph"].pop()
    write(child, "child.cwl")
    document["$graph"][0]["steps"]["echo"]["run"] = "child.cwl"
    report = validate(write(document))
    assert report.exit_code() == 1, report.to_dict()
    assert any(f.rule_id == PROCESS for f in report.findings)


def test_relative_schema_in_remote_document_is_rejected() -> None:
    data = YAML().load(
        "requirements:\n  SchemaDefRequirement:\n    types:\n      - $import: types.yaml\n"
    )
    finding = standalone_checks(Source("https://example.org/application.cwl", data))[0]
    assert finding.rule_id == SCHEMA
    assert finding.location.uri == "https://example.org/application.cwl"


@pytest.mark.parametrize("target", ["tool.cwl", "https://example.org/tool.cwl"])
@pytest.mark.parametrize("root", [False, True])
def test_imported_process_declarations(target: str, root: bool) -> None:
    imported = {"$import": target}
    findings = checks(imported if root else {"$graph": [imported]})
    assert len(findings) == 1
    assert findings[0].rule_id == PROCESS
    assert findings[0].location.path == ("/$import" if root else "/$graph/0/$import")
