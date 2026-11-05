"""Register the trusted Calrissian Dask Gateway requirement schema."""

from __future__ import annotations

from importlib.resources import files
from io import StringIO
from typing import Any

from cwltool.process import get_schema, use_custom_schema
from cwltool.process import (
    supportedProcessRequirements as supported_process_requirements,
)
from ruamel.yaml import YAML

DASK_GATEWAY_REQUIREMENT = (
    "https://calrissian-cwl.github.io/schema#DaskGatewayRequirement"
)
_SCHEMA_NAME = "http://commonwl.org/cwltool"
_EXTENSION_SCHEMAS = {
    "v1.0": "extensions.yml",
    "v1.1": "extensions-v1.1.yml",
    "v1.2": "extensions-v1.2.yml",
}


def _load_yaml(package: str, resource: str) -> dict[str, Any]:
    yaml = YAML(typ="safe")
    loaded = yaml.load(files(package).joinpath(resource).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Schema resource {package}:{resource} is not a mapping.")
    return loaded


def _dump_yaml(document: dict[str, Any]) -> str:
    stream = StringIO()
    YAML(typ="safe").dump(document, stream)
    return stream.getvalue()


def register_dask_schema() -> None:
    """Register the bundled Dask Gateway requirement with cwltool."""
    dask_schema = _load_yaml("eoap_validator.extensions", "dask_gateway.yaml")
    base = dask_schema["$base"]

    for version, extension_resource in _EXTENSION_SCHEMAS.items():
        schema = _load_yaml("cwltool", extension_resource)
        schema["$graph"] = [
            definition for definition in schema["$graph"] if "name" not in definition
        ]
        schema["$graph"].extend(
            dict(definition, name=base + definition["name"])
            for definition in dask_schema["$graph"]
            if "name" in definition
        )
        use_custom_schema(version, _SCHEMA_NAME, _dump_yaml(schema))
        get_schema(version)

    if DASK_GATEWAY_REQUIREMENT not in supported_process_requirements:
        supported_process_requirements.append(DASK_GATEWAY_REQUIREMENT)
