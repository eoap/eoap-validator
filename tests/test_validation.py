import json
from copy import deepcopy

import pytest
from click.testing import CliRunner

from eoap_validator import StagingConfig, validate
from eoap_validator.cli import main
from eoap_validator.report import Finding, Location, Report
from eoap_validator.rules import directory_type


def failures(report):
    return [f for f in report.findings if f.status == "failed"]


def test_valid_combined(document, write):
    report = validate(write(document) + "#main", profiles=("eoap-package", "metadata"))
    assert report.exit_code() == 0, report.to_dict()
    assert not failures(report)
    assert report.entrypoint == "main"
    assert any(
        f.rule_id == "CWL.VALIDATE" and f.status == "passed" for f in report.findings
    )


def test_auto_selection(document, write):
    assert validate(write(document)).entrypoint == "main"


@pytest.mark.parametrize("fragment", ["", "absent", "echo"])
def test_invalid_selection(document, write, fragment):
    report = validate(write(document) + "#" + fragment)
    assert report.exit_code() == 1
    assert any(f.rule_id == "EOAP.ENTRYPOINT" for f in failures(report))


def test_ambiguous_selection(document, write):
    second = deepcopy(document["$graph"][0])
    second["id"] = "other"
    document["$graph"].append(second)
    assert validate(write(document)).exit_code() == 1
    assert validate(write(document) + "#main").exit_code() == 0


def test_unreachable_tool_not_checked(document, write):
    document["$graph"].append(
        {"id": "unused", "class": "CommandLineTool", "inputs": [], "outputs": []}
    )
    report = validate(write(document) + "#main")
    assert not failures(report), report.to_dict()


def test_missing_metadata_does_not_prevent_package_checks(document, write):
    del document["s:author"]
    del document["$graph"][0]["inputs"]["message"]["doc"]
    report = validate(write(document), profiles=("eoap-package", "metadata"))
    rules = {f.rule_id for f in failures(report)}
    assert "TM.METADATA.MODEL" in rules
    assert "EOAP.REQ10.DOC" in rules
    finding = next(f for f in failures(report) if f.rule_id == "EOAP.REQ10.DOC")
    assert finding.location.line is not None


def test_blank_description(document, write):
    document["$graph"][0]["doc"] = "  "
    assert any(
        f.rule_id == "EOAP.REQ9.DOC" for f in failures(validate(write(document)))
    )


def test_version_migration(document, write):
    document["s:version"] = document.pop("s:softwareVersion")
    source = write(document)
    assert validate(source).exit_code() == 0
    report = validate(source, profiles=("metadata",))
    assert report.exit_code() == 1
    assert any(f.rule_id == "TM.VERSION.MIGRATION" for f in failures(report))


def test_inherited_container(document, write):
    document["$graph"][0]["requirements"] = document["$graph"][1]["requirements"]
    document["$graph"][1]["requirements"] = {}
    report = validate(write(document))
    assert report.exit_code() == 0, report.to_dict()


def test_external_run(document, write):
    tool = document["$graph"].pop()
    tool["cwlVersion"] = "v1.2"
    write(tool, "tool.cwl")
    document["$graph"][0]["steps"]["echo"]["run"] = "tool.cwl"
    report = validate(write(document))
    assert report.exit_code() == 0, report.to_dict()
    assert len(report.dependencies) == 2


def test_invalid_cwl_still_inspects_metadata(document, write):
    document["cwlVersion"] = "v1.99"
    del document["s:publisher"]
    report = validate(write(document), profiles=("eoap-package", "metadata"))
    assert report.exit_code() == 1
    assert {f.rule_id for f in failures(report)} >= {
        "CWL.RESOLUTION",
        "TM.METADATA.MODEL",
    }
    assert report.counts["blocked"] > 0


def test_malformed_yaml(tmp_path):
    path = tmp_path / "bad.cwl"
    path.write_text("cwlVersion: [broken")
    report = validate(str(path), profiles=("metadata",))
    assert report.exit_code() == 1
    assert report.counts["blocked"] == 1


def test_missing_file(tmp_path):
    assert validate(str(tmp_path / "missing.cwl")).exit_code() == 2


def test_staging_unknown_and_explicit(document, write):
    source = write(document)
    report = validate(source, profiles=("eoap-staging",))
    assert report.counts["needs-review"] > 0
    assert report.exit_code() == 0
    assert report.exit_code("warning") == 1
    report = validate(
        source,
        profiles=("eoap-staging",),
        staging=StagingConfig(inputs={"main": ["message"]}),
    )
    assert any(f.rule_id == "EOAP.REQ13.INPUT" for f in failures(report))
    report = validate(
        source,
        profiles=("eoap-staging",),
        staging=StagingConfig(inputs={"typo": ["message"]}),
    )
    assert any(f.rule_id == "EOAP.STAGING.TARGET" for f in failures(report))


def test_directory_type_unions():
    assert directory_type(["null", "Directory"])
    assert not directory_type(["Directory", "string"])
    assert not directory_type(["null"])


def test_cli_json_and_file(document, write, tmp_path):
    dest = tmp_path / "report.json"
    result = CliRunner().invoke(
        main, [write(document) + "#main", "--format", "json", "--output", str(dest)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == json.loads(dest.read_text())
    assert payload["entrypoint"] == "main"


def test_report_threshold():
    report = Report(
        source="file:///example.cwl",
        findings=[
            Finding(
                rule_id="test",
                profile="test",
                status="blocked",
                severity="error",
                message="Blocked by another finding",
                location=Location(uri="file:///example.cwl"),
            )
        ],
    )
    assert report.counts["passed"] == 0


def test_bad_configuration():
    with pytest.raises(ValueError):
        validate("unused.cwl", profiles=("unknown",))
    with pytest.raises(ValueError):
        validate("unused.cwl", staging=StagingConfig())


def test_missing_external_dependency(document, write):
    document["$graph"][0]["steps"]["echo"]["run"] = "missing.cwl"
    report = validate(write(document))
    assert report.exit_code() == 2, report.to_dict()


def test_staged_optional_directory_and_output(document, write):
    for process in document["$graph"]:
        process["inputs"]["message"] = {
            "type": ["null", "Directory"],
            "label": "Data",
            "doc": "Staged data.",
        }
    tool = document["$graph"][1]
    tool["outputs"] = {"product": {"type": "Directory", "outputBinding": {"glob": "."}}}
    document["$graph"][0]["steps"]["echo"]["out"] = ["product"]
    report = validate(
        write(document),
        profiles=("eoap-staging",),
        staging=StagingConfig(
            inputs={"main": ["message"], "echo": ["message"]},
            outputs={"echo": ["product"]},
        ),
    )
    assert not failures(report), report.to_dict()
    assert any(
        f.rule_id == "EOAP.REQ14.COVERAGE" and f.status == "needs-review"
        for f in report.findings
    )


def test_source_uri_with_spaces(document, write):
    from pathlib import Path

    source = write(document, "a workflow.cwl")
    assert validate(Path(source).as_uri() + "#main").exit_code() == 0


def test_metadata_quality(document, write):
    document["s:author"] = []
    document["s:description"] = " "
    document["s:softwareHelp"] = {"s:name": "Guide without URL"}
    report = validate(write(document), profiles=("metadata",))
    assert report.exit_code() == 0, report.to_dict()
    assert report.exit_code("warning") == 1
    assert report.counts["needs-review"] >= 3


def test_inherited_hint_is_advisory(document, write):
    document["$graph"][0]["hints"] = document["$graph"][1]["requirements"]
    document["$graph"][1]["requirements"] = {}
    report = validate(write(document))
    assert not failures(report), report.to_dict()
    assert any(f.rule_id == "EOAP.CONTAINER.HINT" for f in report.findings)


def test_two_invocations_preserve_container_context(document, write):
    document["$graph"][1]["requirements"] = {}
    first = document["$graph"][0]["steps"]["echo"]
    second = deepcopy(first)
    first["requirements"] = {"DockerRequirement": {"dockerPull": "alpine:3.20"}}
    document["$graph"][0]["steps"]["other"] = second
    report = validate(write(document))
    docker = [f for f in report.findings if f.rule_id == "EOAP.REQ8.DOCKER"]
    assert {f.status for f in docker} == {"passed", "failed"}


def test_loader_limitation_is_not_invalid_cwl(document, write, monkeypatch):
    from eoap_validator import engine

    def unsupported(*args, **kwargs):
        raise ValueError("Unsupported loader feature")

    monkeypatch.setattr(engine, "load_cwl_from_yaml", unsupported)
    report = validate(write(document) + "#main")
    assert report.exit_code() == 2
    assert any(
        f.rule_id == "CWL.VALIDATE" and f.status == "passed" for f in report.findings
    )


def test_cwl_type_mismatch(document, write):
    document["$graph"][1]["inputs"]["message"] = "int"
    report = validate(write(document))
    assert report.exit_code() == 1
    assert any(
        f.rule_id == "CWL.VALIDATE" and f.status == "failed" for f in report.findings
    )


def test_network_failure_is_incomplete(document, write, monkeypatch):
    from eoap_validator import engine

    monkeypatch.setattr(
        engine,
        "validate_cwl",
        lambda uri: (
            False,
            "Error fetching https://example.org/schema.yaml: Read timed out",
        ),
    )
    report = validate(write(document))
    assert report.exit_code() == 2
    assert any(
        f.rule_id == "CWL.VALIDATE" and f.status == "blocked" for f in report.findings
    )


def test_invalid_cli_json_is_not_polluted(document, write):
    document["cwlVersion"] = "v1.99"
    result = CliRunner().invoke(main, [write(document), "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["exit_code"] == 1


def test_successful_results_describe_observations(document, write):
    report = validate(write(document), profiles=("eoap-package", "metadata"))
    passed = [f for f in report.to_dict()["findings"] if f["status"] == "passed"]
    assert passed
    assert all(f["severity"] == "info" and f["suggestion"] is None for f in passed)
    assert all(
        "must" not in f["message"] and "requires" not in f["message"] for f in passed
    )
    declaration = next(
        f for f in passed if f["rule_id"] == "EOAP.REQ8.REQUIREMENTS.DECLARED"
    )
    assert declaration["message"] == "CommandLineTool 'echo' declares requirements."
    assert report.exit_code("warning") == 0


def test_failure_and_review_severities_are_preserved(document, write):
    tool = document["$graph"][1]
    tool["hints"] = tool.pop("requirements")
    report = validate(write(document))
    declaration = next(
        f for f in report.findings if f.rule_id == "EOAP.REQ8.REQUIREMENTS.DECLARED"
    )
    assert declaration.status == "failed"
    assert declaration.severity == "error"
    assert declaration.suggestion
    review = next(f for f in report.findings if f.rule_id == "EOAP.CONTAINER.HINT")
    assert review.status == "needs-review"
    assert review.severity == "warning"
    assert report.exit_code() == 1


def test_inapplicable_results_are_informational(document, write):
    report = validate(
        write(document), profiles=("eoap-staging",), staging=StagingConfig()
    )
    inapplicable = [f for f in report.findings if f.status == "not-applicable"]
    assert inapplicable
    assert all(f.severity == "info" and f.suggestion is None for f in inapplicable)
    assert report.exit_code("warning") == 0
