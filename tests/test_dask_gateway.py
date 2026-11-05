from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from ruamel.yaml import YAML

from eoap_validator import validate
from eoap_validator.extensions import dask_gateway

if TYPE_CHECKING:
    from conftest import Writer


def add_dask_requirement(document: dict[str, Any]) -> dict[str, Any]:
    document["$namespaces"]["calrissian"] = "https://calrissian-cwl.github.io/schema#"
    requirement = {
        "workerCores": 1,
        "workerCoresLimit": 1,
        "workerMemory": "1GiB",
        "clusterMaxCores": 1,
        "clusterMaxMemory": "1GiB",
    }
    document["$graph"][1]["requirements"]["calrissian:DaskGatewayRequirement"] = (
        requirement
    )
    return requirement


def test_registers_dask_schema_for_stable_cwl_versions(
    monkeypatch: Any,
) -> None:
    registrations: list[tuple[str, str, str]] = []
    loaded: list[str] = []
    supported: list[str] = []
    monkeypatch.setattr(
        dask_gateway,
        "use_custom_schema",
        lambda *args: registrations.append(args),
    )
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


def test_dask_requirement_is_opt_in(document: dict[str, Any], write: Writer) -> None:
    add_dask_requirement(document)
    source = write(document)

    default_report = validate(source)
    enabled_report = validate(
        source, custom_schema_callback=dask_gateway.register_dask_schema
    )

    assert default_report.exit_code() == 1
    assert enabled_report.exit_code() == 0, enabled_report.to_dict()


@pytest.mark.parametrize(
    ("field", "value"),
    [("clusterMaxMemory", None), ("workerCores", "one")],
)
def test_dask_schema_validates_required_field_types(
    document: dict[str, Any], write: Writer, field: str, value: Any
) -> None:
    requirement = add_dask_requirement(document)
    if value is None:
        del requirement[field]
    else:
        requirement[field] = value

    report = validate(
        write(document), custom_schema_callback=dask_gateway.register_dask_schema
    )

    assert report.exit_code() == 1
    finding = next(f for f in report.findings if f.rule_id == "CWL.VALIDATE")
    assert getattr(finding.status, "value", finding.status) == "failed"


def test_dask_schema_does_not_allow_other_mandatory_extensions(
    document: dict[str, Any], write: Writer
) -> None:
    add_dask_requirement(document)
    document["$namespaces"]["other"] = "https://example.org/cwl#"
    document["$graph"][1]["requirements"]["other:UnknownRequirement"] = {}

    report = validate(
        write(document), custom_schema_callback=dask_gateway.register_dask_schema
    )

    assert report.exit_code() == 1


def test_dask_schema_does_not_leak_to_default_validation(
    document: dict[str, Any], write: Writer
) -> None:
    add_dask_requirement(document)
    source = write(document)

    assert (
        validate(
            source, custom_schema_callback=dask_gateway.register_dask_schema
        ).exit_code()
        == 0
    )
    assert validate(source).exit_code() == 1


def test_loader_fallback_receives_schema_callback(
    document: dict[str, Any],
    write: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eoap_validator import engine

    def unsupported(*args: Any, **kwargs: Any) -> None:
        raise ValueError("Unsupported loader feature")

    seen: list[Any] = []

    def validating(uri: str, custom_schema_callback: Any = None) -> tuple[bool, str]:
        seen.append(custom_schema_callback)
        return True, ""

    monkeypatch.setattr(engine, "load_cwl_from_yaml", unsupported)
    monkeypatch.setattr(engine, "validate_cwl", validating)

    report = validate(
        write(document), custom_schema_callback=dask_gateway.register_dask_schema
    )

    operational_failure_exit_code = 2
    assert report.exit_code() == operational_failure_exit_code
    assert seen == [dask_gateway.register_dask_schema]
