# Use the CLI

Install EOAP Validator with Python 3.10 or newer, following the
[README installation instructions](https://github.com/eoap/eoap-validator#install).
Check the available options with:

```sh
eoap-validator --help
```

## Validate a workflow

Pass the CWL source and select its entry Workflow using a URI fragment:

```sh
eoap-validator 'workflow.cwl#main'
```

Replace `workflow.cwl` and `main` with your source and Workflow ID. The source
accepts local paths, `file:` URIs, and HTTP(S) URLs. You may omit the fragment when
the root document contains exactly one Workflow. There is no `--entrypoint`
option.

By default, the CLI runs CWL checks and the `eoap-package` profile. It prints
findings requiring attention and assessment counts without executing the workflow
or pulling container images. Resolving dependencies may require network access.

## Choose profiles

Repeat `--profile` to combine checks. For example, check package rules and
Transpiler-Mate software metadata together:

```sh
eoap-validator 'workflow.cwl#main' \
  --profile eoap-package \
  --profile metadata
```

Explicit profiles replace the default selection, so include `eoap-package` when
you want to retain package checks. CWL checks always run. See
[profiles and reporting](../reference/profiles.md) for each profile's scope.

## Save a JSON report

Use `--output` to save the full report while keeping the text output in your
terminal. Parent directories are created as needed:

```sh
eoap-validator 'workflow.cwl#main' --output build/validation.json
```

To print JSON to standard output instead, use `--format json`:

```sh
eoap-validator 'workflow.cwl#main' --format json > validation.json
```

Dependency diagnostics go to standard error. The full JSON report includes passed
and not-applicable findings that the text output omits.

## Assess staging

Enable `eoap-staging` and declare which parameters are staged in a JSON file such
as `staging.json`:

```json
{
  "inputs": {"main": ["products"], "processor": ["products"]},
  "outputs": {"processor": ["result"]}
}
```

Replace these process and parameter IDs with IDs from your workflow. Keys are
normalized process IDs; values are parameter IDs. Unknown IDs fail validation,
and omitted parameters are not assessed as staged.

```sh
eoap-validator 'workflow.cwl#main' \
  --profile eoap-package \
  --profile eoap-staging \
  --staging staging.json
```

The `--staging` option requires the `eoap-staging` profile. Without applicability
configuration, staging needs review. Complete stage-out file coverage still
requires review of bindings and execution evidence.

## Interpret the result

The default failure threshold is `error`. To also fail on advisory warnings, use:

```sh
eoap-validator 'workflow.cwl#main' --fail-on warning
```

| Exit status | Meaning |
| --- | --- |
| `0` | No findings exceeded the selected failure threshold. |
| `1` | Validation findings reached the selected failure threshold. |
| `2` | A configuration, source, operational, or report-writing error occurred. |

A zero exit status does not certify complete compliance. Inspect `needs-review`
and `blocked` counts in the report. For pipeline integration, see
[use validation in CI](ci.md).
