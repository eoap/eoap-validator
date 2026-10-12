"""Single-document packaging checks against unresolved original YAML."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .models import Severity, Status
from .report import Finding

if TYPE_CHECKING:
    from .source import Source


class StandaloneChecks:
    def __init__(self, source: Source) -> None:
        self.source = source
        self.findings: list[Finding] = []

    def reject(self, node: Any, key: str, path: str, schema: bool) -> None:
        target = node[key]
        if not isinstance(target, str):
            return
        if schema and urlparse(target).scheme in {"http", "https"}:
            return
        if not schema and target.startswith("#"):
            return
        kind = "schema import" if schema else "process reference"
        correction = (
            "Read the referenced schema file and replace this $import with its "
            "schema definitions directly in SchemaDefRequirement.types. Preserve "
            "type names and references, and inline nested local schema imports. "
            "Absolute HTTP(S) schema imports may remain."
            if schema
            else "Embed the referenced CommandLineTool or Workflow in this CWL "
            "document, using an inline run definition or a $graph entry, and "
            "update run to reference its internal #id."
        )
        self.findings.append(
            Finding(
                rule_id="EOAP.SCHEMA.LOCAL_IMPORT"
                if schema
                else "EOAP.PROCESS.EXTERNAL_REFERENCE",
                profile="eoap-package",
                status=Status.FAILED,
                severity=Severity.ERROR,
                message=f"{'Local' if schema else 'External'} {kind} '{target}' breaks the EOAP single-file requirement. "
                + (
                    "Define these schema types inline in SchemaDefRequirement.types."
                    if schema
                    else "Embed the referenced process in this CWL document."
                ),
                suggestion=correction,
                location=self.source.location(f"{path}/{key}", node, key),
            )
        )

    def check_steps(self, steps: Any, path: str) -> None:
        entries = (
            steps.items()
            if isinstance(steps, dict)
            else enumerate(steps)
            if isinstance(steps, list)
            else []
        )
        for name, step in entries:
            if not isinstance(step, dict) or "run" not in step:
                continue
            step_path = f"{path}/{name}"
            if isinstance(step["run"], dict) and "$import" in step["run"]:
                self.reject(step["run"], "$import", f"{step_path}/run", False)
            else:
                self.reject(step, "run", step_path, False)

    def check_graph(self, graph: Any, path: str) -> None:
        if not isinstance(graph, list):
            return
        for index, node in enumerate(graph):
            if isinstance(node, dict) and "$import" in node:
                self.reject(node, "$import", f"{path}/{index}", False)

    def walk(self, value: Any, path: str, schema: bool = False) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                self.walk(item, f"{path}/{index}", schema)
        elif isinstance(value, dict):
            schema = schema or value.get("class") == "SchemaDefRequirement"
            if schema and "$import" in value:
                self.reject(value, "$import", path, True)
            self.check_graph(value.get("$graph"), f"{path}/$graph")
            if value.get("class") == "Workflow":
                self.check_steps(value.get("steps"), f"{path}/steps")
            for key, item in value.items():
                self.walk(
                    item, f"{path}/{key}", schema or key == "SchemaDefRequirement"
                )


def standalone_checks(source: Source) -> list[Finding]:
    """Inspect all declarations, including unreachable processes, without fetching."""
    checks = StandaloneChecks(source)
    if isinstance(source.data, dict) and "$import" in source.data:
        checks.reject(source.data, "$import", "", False)
    checks.walk(source.data, "")
    return checks.findings
