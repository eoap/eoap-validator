"""Static EOAP packaging and explicitly applicable staging rules."""

from __future__ import annotations

from typing import Any
from urllib.parse import urldefrag

from .models import Severity, Status
from .report import Finding, Location, StagingConfig
from .source import Source

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


def reachable(root: Any, index: dict[str, Any]):
    """Yield invocation contexts so inherited requirements remain call-specific."""

    def visit(process, inherited, path, ancestors):
        if process.id in ancestors:
            raise ValueError(f"Recursive workflow reference at {'/'.join(path)}")
        effective = dict(inherited)
        for hint in getattr(process, "hints", None) or []:
            effective["hint:" + hint.class_] = hint
        for req in getattr(process, "requirements", None) or []:
            effective[req.class_] = req
        yield process, effective, path
        for step in getattr(process, "steps", []):
            child_id = str(step.run).removeprefix("#")
            if child_id not in index:
                raise ValueError(f"Unresolved run {step.run}")
            step_requirements = dict(effective)
            for hint in step.hints or []:
                step_requirements["hint:" + hint.class_] = hint
            for req in step.requirements or []:
                step_requirements[req.class_] = req
            yield from visit(
                index[child_id],
                step_requirements,
                path + [step.id],
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
    ):
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
        rule,
        profile,
        status,
        message,
        process,
        field="",
        parameter=None,
        severity="error",
        suggestion=None,
    ):
        self.findings.append(
            Finding(
                rule_id=rule,
                profile=profile,
                status=status,
                severity=severity,
                message=message,
                location=self.location(process, field, parameter),
                suggestion=suggestion,
                instance_path=self.instance_path,
                reference=REFERENCE if rule.startswith("EOAP.REQ") else None,
            )
        )

    def require(
        self, rule, value, message, process, field="", parameter=None, *, passed_message
    ):
        ok = nonempty(value)
        self.add(
            rule,
            "eoap-package",
            "passed" if ok else "failed",
            passed_message if ok else message,
            process,
            field,
            parameter,
            suggestion=None
            if ok
            else f"Provide a nonempty {field or 'value'} in the source document.",
        )

    def package(self, process, effective, path):
        if process.class_ == "Workflow":
            for field in ("id", "label", "doc"):
                self.require(
                    f"EOAP.REQ9.{field.upper()}",
                    getattr(process, field, None),
                    f"Workflow {process.id}: {field} must be present.",
                    process,
                    field,
                    passed_message=f"{process.class_} '{process.id}' has a nonempty {field}.",
                )
            for item in process.inputs:
                for field in ("id", "label", "doc"):
                    self.require(
                        f"EOAP.REQ10.{field.upper()}",
                        getattr(item, field, None),
                        f"Input {item.id}: {field} must be present.",
                        process,
                        "inputs",
                        item,
                        passed_message=f"Input '{item.id}' of Workflow '{process.id}' has a nonempty {field}.",
                    )
        elif process.class_ == "CommandLineTool":
            for field in ("id", "baseCommand"):
                self.require(
                    f"EOAP.REQ8.{field.upper()}",
                    getattr(process, field, None),
                    f"Tool {process.id}: {field} must be present.",
                    process,
                    field,
                    passed_message=f"{process.class_} '{process.id}' has a nonempty {field}.",
                )
            # Empty inputs are legitimate; distinguish declaration from cardinality.
            self.require(
                "EOAP.REQ8.INPUTS",
                process.inputs is not None,
                "Tool inputs must be declared (an empty collection is allowed).",
                process,
                "inputs",
                passed_message=f"CommandLineTool '{process.id}' has an inputs collection (which may be empty).",
            )
            docker = effective.get("DockerRequirement")
            docker = docker or effective.get("hint:DockerRequirement")
            self.require(
                "EOAP.REQ8.DOCKER",
                getattr(docker, "dockerPull", None),
                f"Invocation {'/'.join(path)} requires DockerRequirement.dockerPull.",
                process,
                "requirements",
                passed_message=f"Invocation '{'/'.join(path)}' has an effective DockerRequirement.dockerPull.",
            )
            if docker is not None and "DockerRequirement" not in effective:
                self.add(
                    "EOAP.CONTAINER.HINT",
                    "eoap-package",
                    "needs-review",
                    "Container is advisory (a hint), not an execution requirement.",
                    process,
                    "hints",
                    severity="warning",
                )
        if process.class_ == "Workflow":
            if len(path) == 1:
                self.descriptions(
                    process, "outputs", "EOAP.WORKFLOW.OUTPUT", mandatory=True
                )
            self.descriptions(process, "steps", "EOAP.WORKFLOW.STEP")
        elif process.class_ == "CommandLineTool":
            self.descriptions(process, "inputs", "EOAP.CLT.INPUT")
            self.descriptions(process, "outputs", "EOAP.CLT.OUTPUT")
        self.explicit_declarations(process)

    def descriptions(self, process, collection, prefix, *, mandatory=False):
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
                    process,
                    collection,
                    item,
                    severity="error" if mandatory else "warning",
                    suggestion=None
                    if ok
                    else f"Add a nonempty {field} to '{item.id}'.",
                )

    def explicit_declarations(self, process):
        uri = urldefrag(str(process.loadingOptions.fileuri or self.source.uri))[0]
        source = self.sources.get(uri)
        node = source.process_node(process.id) if source else None
        if node is None:
            self.add(
                "EOAP.SOURCE.DECLARATIONS",
                "eoap-package",
                "blocked",
                "Original process declaration could not be mapped; explicit fields are not assessed.",
                process,
                severity="info",
            )
            return
        self.require(
            "EOAP.SOURCE.ID",
            node.get("id"),
            "Process must have an explicit source ID.",
            process,
            "id",
            passed_message=f"{process.class_} '{process.id}' declares an explicit source ID.",
        )
        if process.class_ == "CommandLineTool":
            self.require(
                "EOAP.REQ8.INPUTS.DECLARED",
                "inputs" in node,
                "CommandLineTool must declare inputs.",
                process,
                "inputs",
                passed_message=f"CommandLineTool '{process.id}' declares inputs.",
            )
            self.require(
                "EOAP.REQ8.REQUIREMENTS.DECLARED",
                "requirements" in node,
                "CommandLineTool must declare requirements under the EOAP package profile.",
                process,
                "requirements",
                passed_message=f"CommandLineTool '{process.id}' declares requirements.",
            )

    def staged(self, process):
        if self.staging is None:
            self.add(
                "EOAP.STAGING.APPLICABILITY",
                "eoap-staging",
                "needs-review",
                "Stage-in/out applicability is unknown. Supply a staging configuration.",
                process,
                severity="warning",
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
                    process,
                    direction,
                    severity="info",
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
                        process,
                        direction,
                    )
                    continue
                ok = directory_type(item.type_)
                self.add(
                    rule,
                    "eoap-staging",
                    "passed" if ok else "failed",
                    (
                        f"Staged {direction} parameter '{name}' has a supported Directory type."
                        if ok
                        else f"Staged {direction} parameter {name} must be Directory or an array/optional Directory type."
                    ),
                    process,
                    direction,
                    item,
                )
                if direction == "outputs":
                    self.add(
                        "EOAP.REQ14.COVERAGE",
                        "eoap-staging",
                        "needs-review",
                        "Output type alone cannot establish complete collection of produced EO files; review bindings and execution evidence.",
                        process,
                        direction,
                        item,
                        severity="warning",
                    )

    def run(self, contexts):
        for process, effective, path in contexts:
            self.instance_path = path
            if "eoap-package" in self.profiles:
                self.package(process, effective, path)
        self.instance_path = []
        if "eoap-staging" in self.profiles:
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
        return self.findings
