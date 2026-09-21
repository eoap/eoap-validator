# Use validation in CI

```sh
eoap-validator 'workflow.cwl#main' \
  --profile eoap-package --profile metadata \
  --output build/validation.json
```

The report is written even when validation findings fail the command. Upload it
as a CI artifact using an always-run step. Use `--format json` for JSON stdout;
diagnostics from dependencies go to stderr. Add `--fail-on warning` when your
pipeline must also reject advisory findings. Keep the default threshold when
readiness advice should inform review without enforcing it.

Profile configuration is versioned with the application. Do not mark unknown
staging as passed; supply reviewed applicability or retain needs-review findings.
