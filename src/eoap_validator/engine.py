"""Independent validation orchestration; no runtime context is constructed."""

from __future__ import annotations

import logging
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from typing import Any
from urllib.parse import urldefrag

import requests
from cwl_loader import load_cwl_from_yaml
from cwltool.main import main as cwltool_main
from ruamel.yaml.error import YAMLError
from session_adapters.file_adapter import FileAdapter

from .metadata import metadata_checks
from .models import Status
from .report import PROFILES, Finding, Location, Report, StagingConfig
from .rules import PackageRules, reachable
from .source import Source, missing_local_references, source_uri


def add(report, rule, status, message, *, severity="error", profile="cwl"):
    report.findings.append(
        Finding(
            rule_id=rule,
            profile=profile,
            status=status,
            severity=severity,
            message=message,
            location=Location(uri=report.source),
        )
    )


def blocked(report, profiles, reason):
    for profile in profiles:
        add(
            report, "PACKAGE.GRAPH", "blocked", reason, severity="info", profile=profile
        )


def validate_cwl(uri: str) -> tuple[bool, str]:
    stdout, stderr = StringIO(), StringIO()
    # cwltool configures its logger. Restore handlers so embedding this library
    # does not leave a closed/captured stream attached to the host application.
    logger = logging.getLogger("cwltool")
    handlers, level = logger.handlers[:], logger.level
    try:
        code = cwltool_main(
            ["--quiet", "--disable-color", "--validate", uri],
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        logger.handlers = handlers
        logger.setLevel(level)
    return code == 0, stderr.getvalue() or stdout.getvalue()


def fetch_failure(message: str) -> bool:
    # schema-salad/cwltool sometimes preserve only a textual fetch error.
    return any(
        marker in message
        for marker in (
            "Error fetching",
            "Failed to fetch",
            "ConnectionError",
            "NameResolutionError",
            "Connection refused",
            "Read timed out",
            "No such file or directory",
        )
    )


def operational(exc: BaseException | None) -> bool:
    pending = [exc] if exc is not None else []
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (OSError, requests.RequestException)) or fetch_failure(
            str(current)
        ):
            return True
        pending.extend(getattr(current, "children", []))
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append(cause)
    return False


def select(source: Source, index: dict[str, Any], fragment: str | None):
    if fragment is not None:
        if not fragment:
            raise ValueError("Empty workflow fragment; use workflow.cwl#main.")
        if fragment not in index:
            raise ValueError(f"Unknown entrypoint {fragment!r}.")
        selected = index[fragment]
        if selected.class_ != "Workflow":
            raise ValueError(f"Entrypoint {fragment!r} is not a Workflow.")
        return selected
    workflows = [
        p
        for p in index.values()
        if p.class_ == "Workflow"
        and urldefrag(str(p.loadingOptions.fileuri))[0] == source.uri
    ]
    if len(workflows) != 1:
        raise ValueError(
            f"Found {len(workflows)} root-document workflows; select one with #<workflow-id>."
        )
    return workflows[0]


def validate(
    location: str,
    *,
    profiles: tuple[str, ...] = ("eoap-package",),
    staging: StagingConfig | None = None,
) -> Report:
    """Inspect a local/HTTP(S) CWL source; validation failures return a report.

    Invalid API configuration raises ValueError. Source/operational failures are
    represented in the report. This API never executes a workflow.
    """
    selected_profiles = set(profiles)
    if not selected_profiles or selected_profiles - set(PROFILES):
        raise ValueError(f"Choose at least one profile from {PROFILES}.")
    if staging is not None and "eoap-staging" not in selected_profiles:
        raise ValueError("Staging configuration requires the eoap-staging profile.")
    uri, fragment = source_uri(location)
    report = Report(
        source=uri,
        entrypoint=fragment,
        profiles={"cwl": "1.0", **dict.fromkeys(sorted(selected_profiles), "1.0")},
        dependencies=[uri],
    )
    if "eoap-package" in selected_profiles:
        report.profiles["eoap-package"] = "1.1"
    for package in ("cwltool", "cwl-loader", "transpiler-mate-api"):
        try:
            report.tool_versions[package] = version(package)
        except PackageNotFoundError:
            report.tool_versions[package] = "unknown"
    try:
        source = Source.read(uri)
    except YAMLError as exc:
        add(report, "CWL.YAML", "failed", str(exc))
        blocked(report, selected_profiles, "YAML could not be parsed.")
        return report
    except (OSError, requests.RequestException, UnicodeError) as exc:
        report.operational_failure = True
        add(report, "SOURCE.READ", "blocked", str(exc))
        blocked(report, selected_profiles, "Source could not be read.")
        return report
    if not isinstance(source.data, dict):
        add(
            report, "CWL.DOCUMENT", "failed", "The CWL document must be a YAML mapping."
        )
        blocked(report, selected_profiles, "No document mapping is available.")
        return report
    report.findings.extend(metadata_checks(source, selected_profiles))
    missing = missing_local_references(source)
    if missing:
        report.operational_failure = True
        report.dependencies.extend(missing)
        for dependency in missing:
            add(
                report,
                "SOURCE.DEPENDENCY",
                "blocked",
                f"Cannot read dependency: {dependency}",
            )
        blocked(
            report,
            selected_profiles - {"metadata"},
            "Dependencies are unavailable.",
        )
        return report
    try:
        with requests.Session() as session:
            session.mount("file://", FileAdapter())
            loaded = load_cwl_from_yaml(deepcopy(source.data), uri=uri, session=session)
    except Exception as exc:
        report.operational_failure = operational(exc)
        if not report.operational_failure:
            # A limitation of our normalizing loader is not evidence of invalid CWL.
            try:
                valid, diagnostics = validate_cwl(
                    uri + ("#" + fragment if fragment else "")
                )
                add(
                    report,
                    "CWL.VALIDATE",
                    "passed" if valid else "failed",
                    "cwltool validation passed." if valid else diagnostics,
                )
                report.operational_failure = valid or fetch_failure(diagnostics)
                if report.operational_failure and not valid:
                    report.findings[-1].status = Status.BLOCKED
            except Exception as validation_exc:
                report.operational_failure = True
                add(report, "CWL.VALIDATE", "blocked", str(validation_exc))
        add(
            report,
            "CWL.RESOLUTION",
            "blocked" if report.operational_failure else "failed",
            str(exc),
        )
        blocked(
            report,
            selected_profiles - {"metadata"},
            "Process resolution did not complete.",
        )
        return report
    processes = loaded if isinstance(loaded, list) else [loaded]
    index = {p.id: p for p in processes}
    if len(index) != len(processes):
        add(
            report,
            "CWL.IDENTITY",
            "failed",
            "Duplicate normalized process IDs; source identity is ambiguous.",
        )
        blocked(
            report,
            selected_profiles - {"metadata"},
            "Ambiguous process identities.",
        )
        return report
    try:
        root = select(source, index, fragment)
    except ValueError as exc:
        add(report, "EOAP.ENTRYPOINT", "failed", str(exc))
        blocked(
            report,
            selected_profiles - {"metadata"},
            "A workflow could not be selected.",
        )
        return report
    report.entrypoint = root.id
    try:
        valid, diagnostics = validate_cwl(f"{uri}#{root.id}")
        add(
            report,
            "CWL.VALIDATE",
            "passed" if valid else "failed",
            "cwltool validation passed." if valid else diagnostics,
        )
    except Exception as exc:
        report.operational_failure = True
        add(report, "CWL.VALIDATE", "blocked", f"cwltool could not complete: {exc}")
        blocked(
            report,
            selected_profiles - {"metadata"},
            "CWL validation did not complete.",
        )
        return report
    if not valid:
        if fetch_failure(diagnostics):
            report.operational_failure = True
            report.findings[-1].status = Status.BLOCKED
        blocked(report, selected_profiles - {"metadata"}, "CWL validation failed.")
        return report
    try:
        contexts = list(reachable(root, index))
    except ValueError as exc:
        add(report, "CWL.GRAPH", "failed", str(exc))
        blocked(
            report,
            selected_profiles - {"metadata"},
            "Selected graph is incomplete.",
        )
        return report
    sources = {uri: source}
    for process, _, _ in contexts:
        process_uri = urldefrag(str(process.loadingOptions.fileuri or uri))[0]
        if process_uri not in report.dependencies:
            report.dependencies.append(process_uri)
        if process_uri not in sources:
            try:
                sources[process_uri] = Source.read(process_uri)
            except (OSError, requests.RequestException, YAMLError, UnicodeError):
                add(
                    report,
                    "SOURCE.LOCATION",
                    "blocked",
                    f"Original source locations unavailable for {process_uri}.",
                    severity="info",
                )
    if "eoap-package" in selected_profiles:
        has_tool = any(p.class_ == "CommandLineTool" for p, _, _ in contexts)
        add(
            report,
            "EOAP.REQ7.STRUCTURE",
            "passed" if has_tool else "failed",
            "Selected graph contains a Workflow and at least one CommandLineTool."
            if has_tool
            else "Selected graph must contain a Workflow and at least one CommandLineTool.",
            profile="eoap-package",
        )
    report.findings.extend(
        PackageRules(source, sources, selected_profiles, staging).run(contexts)
    )
    return report
