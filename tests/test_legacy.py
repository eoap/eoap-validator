"""Regression coverage derived from EOEPCA's legacy fixture and rule intent."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from eoap_validator import validate


@pytest.mark.parametrize(
    "mutation,rule",
    [
        (None, None),
        ("command", "EOAP.REQ8.BASECOMMAND"),
        ("container", "EOAP.REQ8.DOCKER"),
        ("title", "EOAP.REQ9.LABEL"),
        ("input_doc", "EOAP.REQ10.DOC"),
        ("version", "EOAP.REQ11.VERSION"),
    ],
)
def test_legacy_rules(write, mutation, rule):
    data = YAML().load(Path(__file__).with_name("data").joinpath("legacy-valid.cwl"))
    processes = {p["id"]: p for p in data["$graph"]}
    if mutation == "command":
        processes["crop"].pop("baseCommand")
    elif mutation == "container":
        processes["crop"]["hints"].pop("DockerRequirement")
    elif mutation == "title":
        processes["water_bodies"].pop("label")
    elif mutation == "input_doc":
        processes["water_bodies"]["inputs"]["epsg"].pop("doc")
    elif mutation == "version":
        for key in list(data):
            if key.endswith(":softwareVersion") or key.endswith(":version"):
                data.pop(key)
    report = validate(write(data) + "#water_bodies")
    failed = {f.rule_id for f in report.findings if f.status == "failed"}
    if rule:
        assert rule in failed, report.to_dict()
        assert report.exit_code() == 1
    else:
        # The unchanged legacy fixture predates mandatory entry-output descriptions.
        assert failed == {"EOAP.WORKFLOW.OUTPUT.LABEL", "EOAP.WORKFLOW.OUTPUT.DOC"}
        assert report.exit_code() == 1
