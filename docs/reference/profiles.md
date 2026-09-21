# Profiles and reporting contract

Report schema is `1.0`; `eoap-package` is revision `1.1` and other profiles
remain at `1.0`. Validator version starts at
`0.1.0`. Reports include the installed cwltool, cwl-loader and API versions.
Profile changes that alter acceptance behavior require a profile revision.

## CWL foundation

Original YAML is retained for conservative source locations. Duplicate YAML keys
are rejected by ruamel.yaml. The shared loader resolves processes and cwltool
validates the selected original URI, preserving relative-reference semantics.
If the loader fails, cwltool is also consulted: a document accepted by cwltool
but unsupported by the loader is an incomplete assessment, not invalid CWL.

Entrypoint selection is mandatory when multiple root-document Workflows exist.
Rules evaluate reachable processes, preserving invocation-specific inherited
requirements and hints. Parser and loader limitations may block inspection.

## eoap-package

The profile derives from `app-package-validation` requirements 7–14 and
[OGC Best Practice 20-089r1](https://docs.ogc.org/bp/20-089r1.html).
It is a declared static assessment, not certification of all conformance classes.

| Rule family | Meaning |
| --- | --- |
| `EOAP.REQ7.STRUCTURE` | Selected Workflow reaches at least one CommandLineTool. |
| `EOAP.REQ8.*` | Tool ID, baseCommand, declared inputs and requirements, and effective DockerRequirement.dockerPull. Empty input/requirement collections are permitted. |
| `EOAP.REQ9.*` | Workflow ID, label and doc are nonempty. |
| `EOAP.REQ10.*` | Workflow input IDs, labels and docs are nonempty. |
| `EOAP.REQ11.VERSION` | Nonempty application softwareVersion or legacy version metadata. |
| `EOAP.SOURCE.ID` | An explicit process ID is present in the source, rather than only a parser-generated ID. |
| `EOAP.SOURCE.DECLARATIONS` | Declaration checks blocked where a trustworthy source mapping is unavailable. |
| `EOAP.CONTAINER.HINT` | Advisory warning: the declared container is a hint rather than a mandatory requirement. |

Mandatory container requirements inherit through workflow and step invocation
contexts. Hints are tracked separately, with mandatory requirements taking
precedence. The profile checks the literal tool requirements declaration
separately from effective container configuration. The report makes this stricter
packaging requirement visible even where a runner could inherit all requirements.

The legacy `dockerOutputDirectory` prohibition is intentionally not carried over:
it had no OGC requirement reference and belongs in a named platform profile.
Absence of optional legacy metadata is not an error. Resource sizing, fan-out
recommendations and platform compatibility profiles are not implemented here.

The package profile also defines the following documentation rules. These are
profile-specific additions, not newly numbered OGC requirements:

| Rule family | Scope | Missing or blank value |
| --- | --- | --- |
| `EOAP.WORKFLOW.OUTPUT.LABEL` / `.DOC` | Every output of the selected entry Workflow only | Failed, error |
| `EOAP.WORKFLOW.STEP.LABEL` / `.DOC` | Every step of all reachable Workflows, including subworkflows | Needs review, warning |
| `EOAP.CLT.INPUT.LABEL` / `.DOC` | Every input of reachable CommandLineTools | Needs review, warning |
| `EOAP.CLT.OUTPUT.LABEL` / `.DOC` | Every output of reachable CommandLineTools | Needs review, warning |

Nonempty fields pass with informational severity. Whitespace-only values are
considered missing. These rules do not require an otherwise empty collection to
contain parameters or steps. Advisory findings fail CI only with `--fail-on warning`.
Nested workflow outputs are not subject to the mandatory entry-output rule unless
that workflow is selected as the entrypoint.

## eoap-staging

Use explicit `--staging` JSON applicability. Directory, arrays of Directory and
optional Directory types are recognized structurally. A union allowing unrelated
types is rejected for a declared staged parameter. Unknown targets fail.

`EOAP.REQ12.INPUT` and `EOAP.REQ13.INPUT` check declared tool/workflow stage-in
parameters. `EOAP.REQ14.OUTPUT` checks the declared Directory-based output
convention inherited from the legacy validator; it is not proof of Requirement
14's complete collection obligation. `EOAP.REQ14.COVERAGE` always requests review
for declared staged outputs. Neither STAC contents nor actual output files are
inspected. Unspecified applicability requires review rather than a heuristic pass.

## metadata

Metadata is read at application-document scope, normalized with PyLD using
`$namespaces`, and validated by `transpiler_mate.api.SoftwareApplication`.
It is not substituted with workflow label/doc or fabricated default authors.
Required fields are name, description, dateCreated, license, softwareVersion,
softwareHelp, publisher and author, including their nested model requirements.

- `TM.METADATA.MODEL`: exact Pydantic model validation errors.
- `TM.VERSION.MIGRATION`: legacy version does not replace softwareVersion.
- `TM.VERSION.CONSISTENCY`: both properties must agree if both are present.
- `TM.METADATA.QUALITY`: advisory empty values/collections or help entries lacking URLs.
- `METADATA.JSONLD`: metadata expansion failure.

The model allows additional fields. This profile does not impose SemVer, require
ORCID, verify URLs over the network, or certify license compatibility.
Quality checks run after successful model validation.

## Reports

The authoritative output schema is [report.yaml](https://github.com/eoap/eoap-validator/blob/main/schemas/report.yaml),
JSON Schema Draft 2020-12 encoded as YAML. It covers all assessment fields,
findings, source locations, counts, exit code and the `fail_on` threshold.
Both CLI and library serialization pass through the generated `models.Report`.
Library reports now include `fail_on` explicitly, defaulting to `error`.

The task generates models from the schema, including enums and the aliased
`needs-review` / `not-applicable` count fields. `report.py` adds executable
policy on top of generated models without duplicating their field definitions.
Input-only staging configuration remains in `report.py` and is not part of the
output schema. The shared generator enables extra fields on generated classes;
the checked-in JSON Schema remains the strict wire-format contract.

Every finding has rule ID, profile, status, severity, message, source location,
optional correction and optional requirement reference. Locations use one-based
lines and Unicode code-point columns; they are not VS Code UTF-16 ranges.
Unknown locations remain null. Parameter findings currently point to the
parameter declaration, not necessarily the exact missing field.

Statuses: `passed`, `failed`, `needs-review`, `not-applicable`, `blocked`.
Severity describes the reported outcome: `passed` and `not-applicable` checks
use `info` and have no corrective suggestion. Passed messages confirm what was
found. Failed checks retain their rule's failure severity; review findings retain
`warning`. Blocked checks retain the severity of the blocking condition.
Display filtering never changes assessment results.

| Exit code | Meaning |
| --- | --- |
| 0 | Assessment completed without findings above the selected threshold; review findings may remain. |
| 1 | Validation failed the error/warning threshold. |
| 2 | Source/operational failure prevented assessment, or report output failed. |

Reports include root and resolved process-source URIs and directly detected
missing dependency URIs. This is explicitly not a complete `$import`/`$include`
manifest. An unavailable source range does not by itself fail an otherwise
completed semantic assessment.
