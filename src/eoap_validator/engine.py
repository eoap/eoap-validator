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
from .models import Severity as ModelSeverity
from .models import Status
from .report import PROFILES, Finding, Location, Report, Severity, StagingConfig
from .report import Status as FindingStatus
from .rules import Context, PackageRules, reachable
from .source import Source, missing_local_references, source_uri


def add(
    report: Report,
    rule: str,
    status: FindingStatus,
    message: str,
    *,
    severity: Severity = "error",
    profile: str = "cwl",
) -> None:
    report.findings.append(
        Finding(
            rule_id=rule,
            profile=profile,
            status=Status(status),
            severity=ModelSeverity(severity),
            message=message,
            location=Location(uri=report.source),
        )
    )


def blocked(report: Report, profiles: set[str], reason: str) -> None:
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


def select(source: Source, index: dict[str, Any], fragment: str | None) -> Any:
    if fragment is not None:
        if not fragment:
            raise ValueError("Empty workflow fragment; use workflow.cwl#application.")
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
        report.profiles["eoap-package"] = "1.2"
    record_versions(report)
    source = read_source(report, selected_profiles)
    if source is None or not inspect_dependencies(source, report, selected_profiles):
        return report
    processes = resolve_processes(source, report, selected_profiles, fragment)
    if processes is None:
        return report
    contexts = select_contexts(source, processes, report, selected_profiles, fragment)
    if contexts is not None:
        assess_contexts(source, processes, contexts, report, selected_profiles, staging)
    return report


def installed_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def record_versions(report: Report) -> None:
    for package in ("cwltool", "cwl-loader", "transpiler-mate-api"):
        report.tool_versions[package] = installed_version(package)


def read_source(report: Report, selected_profiles: set[str]) -> Source | None:
    uri = report.source
    try:
        source = Source.read(uri)
    except YAMLError as exc:
        add(report, "CWL.YAML", "failed", str(exc))
        blocked(report, selected_profiles, "YAML could not be parsed.")
        return None
    except (OSError, requests.RequestException, UnicodeError) as exc:
        report.operational_failure = True
        add(report, "SOURCE.READ", "blocked", str(exc))
        blocked(report, selected_profiles, "Source could not be read.")
        return None
    if not isinstance(source.data, dict):
        add(
            report, "CWL.DOCUMENT", "failed", "The CWL document must be a YAML mapping."
        )
        blocked(report, selected_profiles, "No document mapping is available.")
        return None
    return source


def inspect_dependencies(
    source: Source, report: Report, selected_profiles: set[str]
) -> bool:
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
        return False
    return True


def resolution_failure(
    exc: Exception, report: Report, selected_profiles: set[str], fragment: str | None
) -> None:
    uri = report.source
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


def resolve_processes(
    source: Source, report: Report, selected_profiles: set[str], fragment: str | None
) -> list[Any] | None:
    uri = report.source
    try:
        with requests.Session() as session:
            session.mount("file://", FileAdapter())
            loaded = load_cwl_from_yaml(deepcopy(source.data), uri=uri, session=session)
    except Exception as exc:
        resolution_failure(exc, report, selected_profiles, fragment)
        return None
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
        return None
    return processes


def select_contexts(
    source: Source,
    processes: list[Any],
    report: Report,
    selected_profiles: set[str],
    fragment: str | None,
) -> list[Context] | None:
    uri = report.source
    index = {p.id: p for p in processes}
    try:
        root = select(source, index, fragment)
    except ValueError as exc:
        add(report, "EOAP.ENTRYPOINT", "failed", str(exc))
        blocked(
            report,
            selected_profiles - {"metadata"},
            "A workflow could not be selected.",
        )
        return None
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
        return None
    if not valid:
        if fetch_failure(diagnostics):
            report.operational_failure = True
            report.findings[-1].status = Status.BLOCKED
        blocked(report, selected_profiles - {"metadata"}, "CWL validation failed.")
        return None
    try:
        contexts = list(reachable(root, index))
    except ValueError as exc:
        add(report, "CWL.GRAPH", "failed", str(exc))
        blocked(
            report,
            selected_profiles - {"metadata"},
            "Selected graph is incomplete.",
        )
        return None
    return contexts


def process_source(uri: str, report: Report) -> Source | None:
    try:
        return Source.read(uri)
    except (OSError, requests.RequestException, YAMLError, UnicodeError):
        add(
            report,
            "SOURCE.LOCATION",
            "blocked",
            f"Original source locations unavailable for {uri}.",
            severity="info",
        )
        return None


def assess_contexts(
    source: Source,
    processes: list[Any],
    contexts: list[Context],
    report: Report,
    selected_profiles: set[str],
    staging: StagingConfig | None,
) -> None:
    uri = report.source
    sources = {uri: source}
    for process in processes:
        process_uri = urldefrag(str(process.loadingOptions.fileuri or uri))[0]
        if process_uri not in report.dependencies:
            report.dependencies.append(process_uri)
        if process_uri not in sources:
            original = process_source(process_uri, report)
            if original is not None:
                sources[process_uri] = original
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
    rules = PackageRules(source, sources, selected_profiles, staging)
    if "eoap-package" in selected_profiles:
        rules.identifiers(processes)
    report.findings.extend(rules.run(contexts))
