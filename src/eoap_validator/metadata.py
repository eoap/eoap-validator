"""Metadata inspection without requiring a valid runtime context."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from pyld import jsonld
from transpiler_mate.api import SoftwareApplication

from .models import Severity as ModelSeverity
from .models import Status as ModelStatus
from .report import DEFAULT_ADVICE, Advice, Finding, Status

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .source import Source

SCHEMA = "https://schema.org/"


def metadata_document(data: dict[str, Any]) -> dict[str, Any]:
    # Match cwl-loader's document-level metadata boundary: never inspect $graph
    # process properties as application metadata, or inject CWL label/doc aliases.
    return {
        key: deepcopy(value)
        for key, value in data.items()
        if key in ("$namespaces", "$schemas", "$base", "@context", "@type")
        or key.startswith(SCHEMA)
        or (":" in key and not key.startswith("$"))
    }


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata_document(data)
    return jsonld.compact(
        metadata, {}, options={"expandContext": metadata.get("$namespaces")}
    )


class MetadataFindings:
    def __init__(self, source: Source) -> None:
        self.source = source
        self.findings: list[Finding] = []

    def add(
        self,
        rule: str,
        profile: str,
        status: Status,
        message: str,
        *,
        key: str | None = None,
        advice: Advice = DEFAULT_ADVICE,
    ) -> None:
        raw_key = key
        if key:
            namespaces = self.source.data.get("$namespaces", {})
            candidates = [SCHEMA + key] + [
                f"{p}:{key}" for p, uri in namespaces.items() if uri == SCHEMA
            ]
            raw_key = next((k for k in candidates if k in self.source.data), None)
        self.findings.append(
            Finding(
                rule_id=rule,
                profile=profile,
                status=ModelStatus(status),
                severity=ModelSeverity(advice.severity),
                message=message,
                location=self.source.location(
                    f"metadata/{key or ''}", self.source.data, raw_key
                ),
                suggestion=advice.suggestion,
            )
        )


def metadata_checks(source: Source, profiles: set[str]) -> list[Finding]:
    collector = MetadataFindings(source)
    add = collector.add
    findings = collector.findings
    try:
        compacted = normalize(source.data)
    except Exception as exc:
        for profile in profiles & {"eoap-package", "metadata"}:
            add(
                "METADATA.JSONLD",
                profile,
                "failed",
                f"Cannot expand application metadata: {exc}",
            )
        return findings

    if "eoap-package" in profiles:
        package_version(compacted, collector)
    if "metadata" not in profiles:
        return findings
    model_metadata(compacted, collector)
    return findings


def package_version(compacted: dict[str, Any], collector: MetadataFindings) -> None:
    add = collector.add
    version = compacted.get(
        SCHEMA + "softwareVersion", compacted.get(SCHEMA + "version")
    )
    valid = isinstance(version, (str, int, float)) and bool(str(version).strip())
    add(
        "EOAP.REQ11.VERSION",
        "eoap-package",
        "passed" if valid else "failed",
        "Application version is present."
        if valid
        else "Missing or empty application version.",
        key="softwareVersion",
        advice=Advice(
            suggestion=None
            if valid
            else "Declare schema:softwareVersion as a quoted string."
        ),
    )


def model_metadata(compacted: dict[str, Any], collector: MetadataFindings) -> None:
    add = collector.add
    if SCHEMA + "version" in compacted and SCHEMA + "softwareVersion" not in compacted:
        add(
            "TM.VERSION.MIGRATION",
            "metadata",
            "failed",
            "schema:version does not satisfy the softwareVersion field.",
            key="version",
            advice=Advice(
                suggestion="Add schema:softwareVersion; keep both values consistent if retaining both."
            ),
        )
    if (
        all(SCHEMA + k in compacted for k in ("version", "softwareVersion"))
        and compacted[SCHEMA + "version"] != compacted[SCHEMA + "softwareVersion"]
    ):
        add(
            "TM.VERSION.CONSISTENCY",
            "metadata",
            "failed",
            "version and softwareVersion disagree.",
            key="softwareVersion",
        )
    try:
        model = SoftwareApplication.model_validate(compacted, by_alias=True)
    except ValidationError as exc:
        for error in exc.errors(include_url=False, include_input=False):
            path = "/".join(str(p).removeprefix(SCHEMA) for p in error["loc"])
            add(
                "TM.METADATA.MODEL",
                "metadata",
                "failed",
                f"{path}: {error['msg']}",
                key=path,
                advice=Advice(
                    suggestion="Correct the field to match the Transpiler-Mate SoftwareApplication model."
                ),
            )
    else:
        add(
            "TM.METADATA.MODEL",
            "metadata",
            "passed",
            "Metadata satisfies SoftwareApplication.",
        )
        for path, message in quality(model.model_dump()):
            add(
                "TM.METADATA.QUALITY",
                "metadata",
                "needs-review",
                message,
                key=path,
                advice=Advice(severity="warning"),
            )


def quality(data: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(data, dict):
        for key, value in data.items():
            yield from quality(value, f"{path}/{key}".strip("/"))
        if "software_help" in data:
            yield from help_quality(data["software_help"])
    elif (isinstance(data, str) and not data.strip()) or data == []:
        yield path, f"{path} is empty despite satisfying its model type."
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from quality(value, f"{path}/{index}")


def help_quality(entries: Any) -> Iterator[tuple[str, str]]:
    for item in entries if isinstance(entries, list) else [entries]:
        if isinstance(item, dict) and not item.get("url"):
            yield "softwareHelp", "A softwareHelp entry has no documentation URL."
