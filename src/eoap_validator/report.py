"""Reporting behavior layered on schema-generated models.

Regenerate models.py with Task; keep executable policy in this module.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from . import models
from .models import Location as Location

Status = Literal["passed", "failed", "needs-review", "not-applicable", "blocked"]
Severity = Literal["error", "warning", "info"]
Profile = Literal["eoap-package", "eoap-staging", "metadata"]
PROFILES = ("eoap-package", "eoap-staging", "metadata")


class Finding(models.Finding):
    model_config = ConfigDict(
        use_enum_values=True, validate_assignment=True, extra="forbid"
    )

    @model_validator(mode="before")
    @classmethod
    def informational_outcome(cls, data: Any) -> Any:
        if isinstance(data, dict):
            status = getattr(data.get("status"), "value", data.get("status"))
            if status in {"passed", "not-applicable"}:
                data = {**data, "severity": "info", "suggestion": None}
        return data


class StagingConfig(BaseModel):
    """Input configuration, separate from the output report schema."""

    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, list[str]] = Field(default_factory=dict)
    outputs: dict[str, list[str]] = Field(default_factory=dict)


class Report(models.ReportData):
    """Incremental assessment with live summaries and generated output validation."""

    model_config = ConfigDict(extra="forbid")

    @field_serializer("findings")
    def serialize_findings(self, findings):
        # Use each finding's serializer, including the runtime enum-value policy.
        return [finding.model_dump(mode="json", by_alias=True) for finding in findings]

    @property
    def counts(self) -> dict[str, int]:
        counts = Counter(
            getattr(item.status, "value", item.status) for item in self.findings
        )
        return {
            key: counts[key]
            for key in ("passed", "failed", "needs-review", "not-applicable", "blocked")
        }

    def exit_code(self, fail_on: Literal["error", "warning"] = "error") -> int:
        if self.operational_failure:
            return 2
        levels = {"error", "warning"} if fail_on == "warning" else {"error"}
        return int(
            any(
                getattr(item.status, "value", item.status) in {"failed", "needs-review"}
                and getattr(item.severity, "value", item.severity) in levels
                for item in self.findings
            )
        )

    def to_dict(self, fail_on: Literal["error", "warning"] = "error") -> dict:
        payload = {
            **self.model_dump(mode="json", by_alias=True),
            "counts": self.counts,
            "exit_code": self.exit_code(fail_on),
            "fail_on": fail_on,
        }
        return models.Report.model_validate(payload).model_dump(
            mode="json", by_alias=True
        )
