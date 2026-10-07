# EOAP Validator

Inspect an EO Application Package before generating publication artifacts or
registering it with a platform. `eoap-validator` is a standalone Python library
and CLI, not a Transpiler-Mate plugin. It validates CWL, evaluates EOAP package
rules derived from the legacy EOEPCA validator, and optionally checks the actual
Transpiler-Mate software metadata model.

## Install

Python 3.10 or newer:

```sh
python -m pip install .
eoap-validator --help
```

This initial checkout requires the accompanying **cwl-loader 0.25.1** file-URI fix.
Until that release is published, install both source checkouts together:

```sh
python -m pip install ../cwl-loader .
```

## Validate a workflow

```sh
eoap-validator 'workflow.cwl#echo-application' \
  --profile eoap-package \
  --profile metadata \
  --output build/validation.json
```

The source accepts local paths, `file:` URIs and HTTP(S) URLs. The fragment selects
one Workflow; without a fragment, exactly one Workflow must exist in the root
document. Empty, unknown and non-Workflow selections are errors. There is no
`--entrypoint` option. Rules inspect the selected reachable graph, except process IDs are checked
across all resolved processes; parsing and
resolution can still encounter invalid declarations elsewhere in the document.

The `eoap-package` profile requires nonempty `label` and `doc` on entry-workflow
outputs. It recommends these fields on reachable workflow steps and on
CommandLineTool inputs and outputs; missing recommendations produce warnings.

The default profile is `eoap-package`. CWL checks always run. A package that lacks
Transpiler-Mate metadata can still receive EOAP findings. No workflow is executed
and no container image is pulled by the validator. Fetching CWL dependencies or
JSON-LD contexts may require network access.

```sh
# Machine-readable stdout, including findings and assessment coverage:
eoap-validator 'workflow.cwl#echo-application' --format json

# Make advisory findings fail CI as well:
eoap-validator 'workflow.cwl#echo-application' --fail-on warning
```

An exit status of zero means the selected failure threshold was not exceeded;
it is not a certificate of complete EOAP or platform compliance. Always inspect
`needs-review` and `blocked` counts in the report.

## Staging applicability

Staging is conditional: a Directory parameter alone does not prove correct
staging. Enable the profile and supply a JSON file identifying staged parameters:

```json
{
  "inputs": {"echo-application": ["products"], "processor": ["products"]},
  "outputs": {"processor": ["result"]}
}
```

```sh
eoap-validator 'workflow.cwl#echo-application' --profile eoap-package \
  --profile eoap-staging --staging staging.json --output validation.json
```

Keys are normalized process IDs and values are parameter IDs. Configuration is
an explicit applicability declaration: omitted parameters are not assessed as
staged. Unknown processes/parameters fail. Without configuration, staging is
reported as needing review. Complete stage-out file coverage always requires
review of bindings and execution evidence.

## Library

```python
from eoap_validator import validate

report = validate("workflow.cwl#echo-application", profiles=("eoap-package", "metadata"))
print(report.to_dict())
raise SystemExit(report.exit_code())
```

See [profiles](docs/reference/profiles.md), [architecture and boundaries](docs/explanation/architecture.md),
and [CI usage](docs/how-to/ci.md). The library returns structured failures for bad
input documents; invalid API configuration raises `ValueError`.

## Development

```sh
python -m pip install ../cwl-loader '.[test]'
pytest
ruff check src tests
ruff format --check src tests
mypy src
python -m build
```

The serialized report contract is [schemas/report.yaml](schemas/report.yaml), a
JSON Schema (Draft 2020-12) written as YAML. Regenerate its Pydantic models with:

```sh
task generate_ms_skeleton
```

This runs the shared `json:create_models` task and writes
`src/eoap_validator/models.py`. Do not edit generated models manually. Custom
summary, exit-code and finding-normalization behavior lives in `report.py`.
`report.to_dict(fail_on="warning")` returns a generated-model-validated report
with matching counts, exit code and failure threshold.

Alternatively use `hatch run test:test` and `task` after dependencies are available.
The regression suite includes an attributed fixture from EOEPCA's legacy project;
see [NOTICE](NOTICE). No legacy implementation is vendored.

Licensed under Apache-2.0.

## Mandatory scheduling and process identifier policy

The `eoap-package` profile requires explicit `coresMin`, `coresMax`, `ramMin`,
and `ramMax` in an effective `ResourceRequirement` under `requirements` for
every reachable CommandLineTool invocation. Workflow and step requirements
inherit; a more local ResourceRequirement replaces the inherited one as a whole.
Hints do not satisfy this policy. Missing fields produce
`SCHEDULING.RESOURCE.<field>` errors. CWL expressions are accepted as declarations;
the validator does not evaluate their runtime values.

All resolved Workflows and CommandLineTools, including internal and unreachable
processes, must use an ID other than `main`. Violations produce
`SERVICE.PROCESS.ID` errors. Both policies are mandatory profile additions for
processing-service registration and Calrissian scheduling on Kubernetes, beyond
strict OGC 20-089r1 conformance. These checks do not run in metadata-only or
staging-only assessments.
