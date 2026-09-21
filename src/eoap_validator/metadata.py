"""Metadata inspection without requiring a valid runtime context."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError
from pyld import jsonld
from transpiler_mate.api import SoftwareApplication

from .models import Severity as ModelSeverity
from .models import Status as ModelStatus
from .report import Finding, Severity, Status
from .source import Source

SCHEMA = "https://schema.org/"


def metadata_document(data: dict) -> dict:
    # Match cwl-loader's document-level metadata boundary: never inspect $graph
    # process properties as application metadata, or inject CWL label/doc aliases.
    return {
        key: deepcopy(value)
        for key, value in data.items()
        if key in ("$namespaces", "$schemas", "$base", "@context", "@type")
        or key.startswith(SCHEMA)
        or (":" in key and not key.startswith("$"))
    }


def normalize(data: dict) -> dict:
    metadata = metadata_document(data)
    return jsonld.compact(
        metadata, {}, options={"expandContext": metadata.get("$namespaces")}
    )


def metadata_checks(source: Source, profiles: set[str]) -> list[Finding]:
    findings: list[Finding] = []

    def add(
        rule: str,
        profile: str,
        status: Status,
        message: str,
        key: str | None = None,
        severity: Severity = "error",
        suggestion: str | None = None,
    ):
        raw_key = key
        if key:
            namespaces = source.data.get("$namespaces", {})
            candidates = [SCHEMA + key] + [
                f"{p}:{key}" for p, uri in namespaces.items() if uri == SCHEMA
            ]
            raw_key = next((k for k in candidates if k in source.data), None)
        findings.append(
            Finding(
                rule_id=rule,
                profile=profile,
                status=ModelStatus(status),
                severity=ModelSeverity(severity),
                message=message,
                location=source.location(f"metadata/{key or ''}", source.data, raw_key),
                suggestion=suggestion,
            )
        )

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
            "softwareVersion",
            suggestion=None
            if valid
            else "Declare schema:softwareVersion as a quoted string.",
        )
    if "metadata" not in profiles:
        return findings
    if SCHEMA + "version" in compacted and SCHEMA + "softwareVersion" not in compacted:
        add(
            "TM.VERSION.MIGRATION",
            "metadata",
            "failed",
            "schema:version does not satisfy the softwareVersion field.",
            "version",
            suggestion="Add schema:softwareVersion; keep both values consistent if retaining both.",
        )
    if all(SCHEMA + k in compacted for k in ("version", "softwareVersion")):
        if compacted[SCHEMA + "version"] != compacted[SCHEMA + "softwareVersion"]:
            add(
                "TM.VERSION.CONSISTENCY",
                "metadata",
                "failed",
                "version and softwareVersion disagree.",
                "softwareVersion",
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
                path,
                suggestion="Correct the field to match the Transpiler-Mate SoftwareApplication model.",
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
                path,
                "warning",
            )
    return findings


def quality(data: Any, path: str = ""):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from quality(value, f"{path}/{key}".strip("/"))
        if "software_help" in data:
            entries = data["software_help"]
            for item in entries if isinstance(entries, list) else [entries]:
                if isinstance(item, dict) and not item.get("url"):
                    yield (
                        "softwareHelp",
                        "A softwareHelp entry has no documentation URL.",
                    )
    elif (isinstance(data, str) and not data.strip()) or data == []:
        yield path, f"{path} is empty despite satisfying its model type."
    elif isinstance(data, list):
        for index, value in enumerate(data):
            yield from quality(value, f"{path}/{index}")
