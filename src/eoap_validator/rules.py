"""Static EOAP packaging and explicitly applicable staging rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urldefrag

from .models import Severity, Status
from .report import DEFAULT_ADVICE, Advice, Finding, Location, StagingConfig
from .report import Status as FindingStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .source import Source

Context = tuple[Any, dict[str, Any], list[str]]

REFERENCE = "https://docs.ogc.org/bp/20-089r1.html"


def nonempty(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(nonempty(v) for v in value)
    return value is not None


def directory_type(value: Any) -> bool:
    if value == "Directory":
        return True
    if isinstance(value, list):
        alternatives = [v for v in value if v != "null"]
        return bool(alternatives) and all(directory_type(v) for v in alternatives)
    if getattr(value, "type_", None) == "array":
        return directory_type(value.items)
    return False


def effective_requirements(owner: Any, inherited: dict[str, Any]) -> dict[str, Any]:
    effective = dict(inherited)
    for hint in getattr(owner, "hints", None) or []:
        effective["hint:" + hint.class_] = hint
    for requirement in getattr(owner, "requirements", None) or []:
        effective[requirement.class_] = requirement
    return effective


def reachable(root: Any, index: dict[str, Any]) -> Iterator[Context]:
    """Yield invocation contexts so inherited requirements remain call-specific."""

    def visit(
        process: Any, inherited: dict[str, Any], path: list[str], ancestors: set[str]
    ) -> Iterator[Context]:
        if process.id in ancestors:
            raise ValueError(f"Recursive workflow reference at {'/'.join(path)}")
        effective = effective_requirements(process, inherited)
        yield process, effective, path
        for step in getattr(process, "steps", []):
            child_id = str(step.run).removeprefix("#")
            if child_id not in index:
                raise ValueError(f"Unresolved run {step.run}")
            step_requirements = effective_requirements(step, effective)
            yield from visit(
                index[child_id],
                step_requirements,
                [*path, step.id],
                ancestors | {process.id},
            )

    yield from visit(root, {}, [root.id], set())


class PackageRules:
    def __init__(
        self,
        source: Source,
        sources: dict[str, Source],
        profiles: set[str],
        staging: StagingConfig | None,
    ) -> None:
        self.source = source
        self.sources = sources
        self.profiles = profiles
        self.staging = staging
        self.findings: list[Finding] = []
        self.instance_path: list[str] = []

    def location(
        self, process: Any, field: str = "", parameter: Any = None
    ) -> Location:
        uri = urldefrag(str(process.loadingOptions.fileuri or self.source.uri))[0]
        source = self.sources.get(uri)
        path = f"{process.id}/{field}".rstrip("/")
        if parameter is not None:
            path += f"/{parameter.id}"
        if source is None:
            return Location(uri=uri, path=path)
        node = source.process_node(process.id)
        if parameter is not None and node is not None:
            collection = node.get(field, {})
            if isinstance(collection, dict):
                return source.location(path, collection, parameter.id)
            if isinstance(collection, list):
                matches = [
                    n
                    for n in collection
                    if isinstance(n, dict)
                    and n.get("id", "").removeprefix("#") == parameter.id
                ]
                return source.location(path, matches[0] if len(matches) == 1 else None)
        return source.location(path, node, field if node and field in node else None)

    def add(
        self,
        rule: str,
        profile: str,
        status: FindingStatus,
        message: str,
        location: Location,
        *,
        advice: Advice = DEFAULT_ADVICE,
    ) -> None:
        self.findings.append(
            Finding(
                rule_id=rule,
                profile=profile,
                status=Status(status),
                severity=Severity(advice.severity),
                message=message,
                location=location,
                suggestion=advice.suggestion,
                instance_path=self.instance_path,
                reference=REFERENCE if rule.startswith("EOAP.REQ") else None,
            )
        )

    def require(
        self,
        rule: str,
        value: Any,
        message: str,
        location: Location,
        *,
        passed_message: str,
        field: str = "",
    ) -> None:
        ok = nonempty(value)
        self.add(
            rule,
            "eoap-package",
            "passed" if ok else "failed",
            passed_message if ok else message,
            location,
            advice=Advice(
                suggestion=None
                if ok
                else f"Provide a nonempty {field or 'value'} in the source document."
            ),
        )

    def package(self, process: Any, effective: dict[str, Any], path: list[str]) -> None:
        if process.class_ == "Workflow":
            self.workflow(process, path)
        elif process.class_ == "CommandLineTool":
            self.tool(process, effective, path)
        self.explicit_declarations(process)

    def workflow(self, process: Any, path: list[str]) -> None:
        for field in ("id", "label", "doc"):
            self.require(
                f"EOAP.REQ9.{field.upper()}",
                getattr(process, field, None),
                f"Workflow {process.id}: {field} must be present.",
                self.location(process, field=field),
                passed_message=f"{process.class_} '{process.id}' has a nonempty {field}.",
                field=field,
            )
        for item in process.inputs:
            for field in ("id", "label", "doc"):
                self.require(
                    f"EOAP.REQ10.{field.upper()}",
                    getattr(item, field, None),
                    f"Input {item.id}: {field} must be present.",
                    self.location(process, field="inputs", parameter=item),
                    passed_message=f"Input '{item.id}' of Workflow '{process.id}' has a nonempty {field}.",
                    field="inputs",
                )
        if len(path) == 1:
            self.descriptions(
                process, "outputs", "EOAP.WORKFLOW.OUTPUT", mandatory=True
            )
        self.descriptions(process, "steps", "EOAP.WORKFLOW.STEP")

    def tool(self, process: Any, effective: dict[str, Any], path: list[str]) -> None:
        for field in ("id", "baseCommand"):
            self.require(
                f"EOAP.REQ8.{field.upper()}",
                getattr(process, field, None),
                f"Tool {process.id}: {field} must be present.",
                self.location(process, field=field),
                passed_message=f"{process.class_} '{process.id}' has a nonempty {field}.",
                field=field,
            )
        # Empty inputs are legitimate; distinguish declaration from cardinality.
        self.require(
            "EOAP.REQ8.INPUTS",
            process.inputs is not None,
            "Tool inputs must be declared (an empty collection is allowed).",
            self.location(process, field="inputs"),
            passed_message=f"CommandLineTool '{process.id}' has an inputs collection (which may be empty).",
            field="inputs",
        )
        self.resources(process, effective, path)
        docker = effective.get("DockerRequirement")
        docker = docker or effective.get("hint:DockerRequirement")
        self.require(
            "EOAP.REQ8.DOCKER",
            getattr(docker, "dockerPull", None),
            f"Invocation {'/'.join(path)} requires DockerRequirement.dockerPull.",
            self.location(process, field="requirements"),
            passed_message=f"Invocation '{'/'.join(path)}' has an effective DockerRequirement.dockerPull.",
            field="requirements",
        )
        if docker is not None and "DockerRequirement" not in effective:
            self.add(
                "EOAP.CONTAINER.HINT",
                "eoap-package",
                "needs-review",
                "Container is advisory (a hint), not an execution requirement.",
                self.location(process, field="hints"),
                advice=Advice(severity="warning"),
            )
        self.descriptions(process, "inputs", "EOAP.CLT.INPUT")
        self.descriptions(process, "outputs", "EOAP.CLT.OUTPUT")

    def resources(
        self, process: Any, effective: dict[str, Any], path: list[str]
    ) -> None:
        resources = effective.get("ResourceRequirement")
        for field in ("coresMin", "coresMax", "ramMin", "ramMax"):
            ok = resources is not None and getattr(resources, field, None) is not None
            self.add(
                f"SCHEDULING.RESOURCE.{field}",
                "eoap-package",
                "passed" if ok else "failed",
                f"Invocation '{'/'.join(path)}' declares ResourceRequirement.{field}."
                if ok
                else f"Invocation '{'/'.join(path)}' must declare ResourceRequirement.{field} for Calrissian scheduling.",
                self.location(process, field="requirements"),
                advice=Advice(
                    suggestion=None
                    if ok
                    else f"Define {field} in an effective ResourceRequirement under requirements (Workflow, step, or tool)."
                ),
            )

    def identifiers(self, processes: list[Any]) -> None:
        """Check all resolved processes, including those outside the selected graph."""
        for process in processes:
            if process.class_ not in {"Workflow", "CommandLineTool"}:
                continue
            identifier = str(process.id)
            fragment = urldefrag(identifier)[1]
            ok = (fragment or identifier).rstrip("/").rsplit("/", 1)[-1] != "main"
            self.add(
                "SERVICE.PROCESS.ID",
                "eoap-package",
                "passed" if ok else "failed",
                f"{process.class_} '{identifier}' has an application-specific process ID."
                if ok
                else f"{process.class_} '{identifier}' must not use the process ID 'main'.",
                self.location(process, field="id"),
                advice=Advice(
                    suggestion=None
                    if ok
                    else "Use a descriptive application-specific process ID and update references to it."
                ),
            )

    def descriptions(
        self, process: Any, collection: str, prefix: str, *, mandatory: bool = False
    ) -> None:
        """Profile-specific documentation rules, distinct from numbered OGC rules."""
        for item in getattr(process, collection):
            for field in ("label", "doc"):
                ok = nonempty(getattr(item, field, None))
                subject = (
                    f"{process.class_} '{process.id}' {collection} entry '{item.id}'"
                )
                self.add(
                    f"{prefix}.{field.upper()}",
                    "eoap-package",
                    "passed" if ok else ("failed" if mandatory else "needs-review"),
                    f"{subject} has a nonempty {field}."
                    if ok
                    else f"{subject} is missing a nonempty {field} ({'required' if mandatory else 'recommended'}).",
                    self.location(process, field=collection, parameter=item),
                    advice=Advice(
                        severity="error" if mandatory else "warning",
                        suggestion=None
                        if ok
                        else f"Add a nonempty {field} to '{item.id}'.",
                    ),
                )

    def explicit_declarations(self, process: Any) -> None:
        uri = urldefrag(str(process.loadingOptions.fileuri or self.source.uri))[0]
        source = self.sources.get(uri)
        node = source.process_node(process.id) if source else None
        if node is None:
            self.add(
                "EOAP.SOURCE.DECLARATIONS",
                "eoap-package",
                "blocked",
                "Original process declaration could not be mapped; explicit fields are not assessed.",
                self.location(process),
                advice=Advice(severity="info"),
            )
            return
        self.require(
            "EOAP.SOURCE.ID",
            node.get("id"),
            "Process must have an explicit source ID.",
            self.location(process, field="id"),
            passed_message=f"{process.class_} '{process.id}' declares an explicit source ID.",
            field="id",
        )
        if process.class_ == "CommandLineTool":
            self.require(
                "EOAP.REQ8.INPUTS.DECLARED",
                "inputs" in node,
                "CommandLineTool must declare inputs.",
                self.location(process, field="inputs"),
                passed_message=f"CommandLineTool '{process.id}' declares inputs.",
                field="inputs",
            )
            self.require(
                "EOAP.REQ8.REQUIREMENTS.DECLARED",
                "requirements" in node,
                "CommandLineTool must declare requirements under the EOAP package profile.",
                self.location(process, field="requirements"),
                passed_message=f"CommandLineTool '{process.id}' declares requirements.",
                field="requirements",
            )

    def staged(self, process: Any) -> None:
        if self.staging is None:
            self.add(
                "EOAP.STAGING.APPLICABILITY",
                "eoap-staging",
                "needs-review",
                "Stage-in/out applicability is unknown. Supply a staging configuration.",
                self.location(process),
                advice=Advice(severity="warning"),
            )
            return
        for direction in ("inputs", "outputs"):
            configured = getattr(self.staging, direction).get(process.id, [])
            if not configured:
                self.add(
                    "EOAP.STAGING.APPLICABILITY",
                    "eoap-staging",
                    "not-applicable",
                    f"No staged {direction} declared for {process.id} in the supplied configuration.",
                    self.location(process, field=direction),
                    advice=Advice(severity="info"),
                )
            index = {item.id: item for item in getattr(process, direction)}
            for name in configured:
                item = index.get(name)
                rule = (
                    "EOAP.REQ14.OUTPUT"
                    if direction == "outputs"
                    else (
                        "EOAP.REQ13.INPUT"
                        if process.class_ == "Workflow"
                        else "EOAP.REQ12.INPUT"
                    )
                )
                if item is None:
                    self.add(
                        "EOAP.STAGING.TARGET",
                        "eoap-staging",
                        "failed",
                        f"Unknown {direction} parameter {name} in staging configuration.",
                        self.location(process, field=direction),
                    )
                    continue
                ok = directory_type(item.type_)
                self.add(
                    rule,
                    "eoap-staging",
                    "passed" if ok else "failed",
                    f"Staged {direction} parameter '{name}' has a supported Directory type."
                    if ok
                    else f"Staged {direction} parameter {name} must be Directory or an array/optional Directory type.",
                    self.location(process, field=direction, parameter=item),
                )
                if direction == "outputs":
                    self.add(
                        "EOAP.REQ14.COVERAGE",
                        "eoap-staging",
                        "needs-review",
                        "Output type alone cannot establish complete collection of produced EO files; review bindings and execution evidence.",
                        self.location(process, field=direction, parameter=item),
                        advice=Advice(severity="warning"),
                    )

    def run(self, contexts: list[Context]) -> list[Finding]:
        for process, effective, path in contexts:
            self.instance_path = path
            if "eoap-package" in self.profiles:
                self.package(process, effective, path)
        self.instance_path = []
        if "eoap-staging" in self.profiles:
            self.staging_contexts(contexts)
        return self.findings

    def staging_contexts(self, contexts: list[Context]) -> None:
        processes = {p.id: p for p, _, _ in contexts}
        for process in processes.values():
            self.staged(process)
        if self.staging:
            for name in set(self.staging.inputs) | set(self.staging.outputs):
                if name not in processes:
                    self.findings.append(
                        Finding(
                            rule_id="EOAP.STAGING.TARGET",
                            profile="eoap-staging",
                            status=Status.FAILED,
                            severity=Severity.ERROR,
                            message=f"Staging process {name} is outside the selected graph.",
                            location=Location(uri=self.source.uri, path=name),
                        )
                    )
