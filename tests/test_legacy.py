"""Regression coverage derived from EOEPCA's legacy fixture and rule intent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from ruamel.yaml import YAML

from eoap_validator import validate

if TYPE_CHECKING:
    from conftest import Writer


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
def test_legacy_rules(write: Writer, mutation: str | None, rule: str | None) -> None:
    data = YAML().load(Path(__file__).with_name("data").joinpath("legacy-valid.cwl"))
    mutate_legacy(data, mutation)
    report = validate(write(data) + "#water_bodies")
    failed = {
        f.rule_id
        for f in report.findings
        if getattr(f.status, "value", f.status) == "failed"
    }
    if rule:
        assert rule in failed, report.to_dict()
        assert report.exit_code() == 1
    else:
        # The unchanged legacy fixture predates mandatory entry-output descriptions and explicit resource minima.
        assert failed == {
            "EOAP.WORKFLOW.OUTPUT.LABEL",
            "EOAP.WORKFLOW.OUTPUT.DOC",
            *(f"SCHEDULING.RESOURCE.{field}" for field in ("coresMin", "ramMin")),
        }
        assert report.exit_code() == 1


def mutate_legacy(data: dict[str, Any], mutation: str | None) -> None:
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
        version_keys = [
            key for key in data if key.endswith((":softwareVersion", ":version"))
        ]
        for key in version_keys:
            data.pop(key)
