from __future__ import annotations

from typing import Any

from ruamel.yaml import YAML

from eoap_validator.extensions import dask_gateway


def test_registers_dask_schema_for_stable_cwl_versions(
    monkeypatch: Any,
) -> None:
    registrations: list[tuple[str, str, str]] = []
    loaded: list[str] = []
    supported: list[str] = []
    monkeypatch.setattr(dask_gateway, "use_custom_schema", lambda *args: registrations.append(args))
    monkeypatch.setattr(dask_gateway, "get_schema", loaded.append)
    monkeypatch.setattr(dask_gateway, "supported_process_requirements", supported)

    dask_gateway.register_dask_schema()
    dask_gateway.register_dask_schema()

    assert [version for version, _, _ in registrations] == [
        "v1.0",
        "v1.1",
        "v1.2",
        "v1.0",
        "v1.1",
        "v1.2",
    ]
    assert loaded == ["v1.0", "v1.1", "v1.2"] * 2
    assert supported == [dask_gateway.DASK_GATEWAY_REQUIREMENT]

    yaml = YAML(typ="safe")
    for _, schema_name, schema_text in registrations:
        assert schema_name == "http://commonwl.org/cwltool"
        schema = yaml.load(schema_text)
        requirement = next(
            definition
            for definition in schema["$graph"]
            if definition.get("name") == dask_gateway.DASK_GATEWAY_REQUIREMENT
        )
        assert requirement["extends"] == "cwl:ProcessRequirement"
        assert set(requirement["fields"]) == {
            "class",
            "workerCores",
            "workerCoresLimit",
            "workerMemory",
            "clusterMaxCores",
            "clusterMaxMemory",
        }
