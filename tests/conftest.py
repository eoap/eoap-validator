from copy import deepcopy

import pytest
from ruamel.yaml import YAML


@pytest.fixture
def document():
    return {
        "cwlVersion": "v1.2",
        "$namespaces": {"s": "https://schema.org/"},
        "s:name": "Echo application",
        "s:description": "An example EOAP.",
        "s:softwareVersion": "1.0.0",
        "s:dateCreated": "2026-09-21",
        "s:license": "https://spdx.org/licenses/Apache-2.0",
        "s:softwareHelp": {"s:name": "Guide", "s:url": "https://example.org/help"},
        "s:publisher": {"s:name": "Example"},
        "s:author": {
            "s:givenName": "Ada",
            "s:familyName": "Example",
            "s:email": "ada@example.org",
            "s:affiliation": {"s:name": "Example"},
        },
        "$graph": [
            {
                "class": "Workflow",
                "id": "main",
                "label": "Echo",
                "doc": "Echo a message.",
                "inputs": {
                    "message": {
                        "type": "string",
                        "label": "Message",
                        "doc": "Text to echo.",
                    }
                },
                "outputs": [],
                "steps": {
                    "echo": {
                        "run": "#echo",
                        "in": {"message": "message"},
                        "out": [],
                        "label": "Echo message",
                        "doc": "Run the echo tool.",
                    }
                },
            },
            {
                "class": "CommandLineTool",
                "id": "echo",
                "baseCommand": "echo",
                "requirements": {"DockerRequirement": {"dockerPull": "alpine:3.20"}},
                "inputs": {
                    "message": {
                        "type": "string",
                        "label": "Message",
                        "doc": "Text to echo.",
                    }
                },
                "outputs": [],
            },
        ],
    }


@pytest.fixture
def write(tmp_path):
    def save(data, name="workflow.cwl"):
        path = tmp_path / name
        with path.open("w") as stream:
            YAML().dump(deepcopy(data), stream)
        return str(path)

    return save
