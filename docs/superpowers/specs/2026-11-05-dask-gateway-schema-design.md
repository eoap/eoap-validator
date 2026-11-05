# Built-in Dask Gateway Schema Support

## Intent

Allow operators to validate the Calrissian `DaskGatewayRequirement` explicitly with `--enable-dask-gateway`, without installing or importing the Calrissian Dask runtime package. This closes issue #11 while preserving strict rejection of unknown mandatory requirements by default.

## Goals

- Add a purpose-specific `--enable-dask-gateway` CLI flag.
- Register the Dask Gateway CWL schema with cwltool only when requested.
- Apply the schema consistently to normal validation and loader-fallback validation.
- Validate the extension's fields, not merely recognize its class URI.
- Keep validation independent of workflow execution, Dask, Kubernetes, and Calrissian runtime dependencies.

## Non-goals

- A general extension/plugin framework.
- Entry-point discovery or arbitrary `module:function` imports.
- Automatic activation based on CWL document content.
- Dask workflow execution or runtime-capability checks.
- Extension-specific normalization in `cwl-loader`; its opaque preservation behavior remains unchanged.

## Constraints and trust boundary

- Default behavior remains unchanged: the Dask Gateway requirement and all other unknown mandatory requirements are rejected.
- The bundled schema is trusted project code and is enabled only by an explicit operator flag.
- cwltool schema registration mutates process-global state, so schema setup and validation must be serialized and each invocation must explicitly select either the built-in callback or cwltool's standard schema reset.
- The bundled schema is derived from Duke-GCB/calrissian commit `771768852f0f69aac84a63d8f2ca62e16a22b36a`; its origin and synchronization requirement must be documented.

## Approaches considered

1. A generic `module:function` provider option would work immediately but exposes unnecessary arbitrary import surface.
2. Package entry points would give controlled discovery but require an extension ecosystem and a separately released provider package.
3. A built-in Dask Gateway schema and one explicit flag is selected because the project owns this extension and does not foresee other extensions.

## Design

Add `eoap_validator.extensions.dask_gateway.register_dask_schema()`. It loads the bundled schema, merges its named definitions into cwltool's extension schema for CWL 1.0, 1.1, and 1.2, registers each result with `use_custom_schema()`, primes it with `get_schema()`, and marks the exact requirement URI as supported.

The engine accepts an internal optional zero-argument schema callback and forwards it through every cwltool validation route. A module-level reentrant lock covers the complete cwltool invocation because registration, schema selection, validation, and logger configuration all touch global state.

The CLI maps `--enable-dask-gateway` directly to the built-in callback. No external package is imported. Documentation states that the flag validates the schema contract only and does not prove that a runtime can execute the requirement.

## Validation

- The issue #11 reproducer fails without the flag and passes CWL validation with it.
- Missing or incorrectly typed Dask fields fail with cwltool diagnostics.
- An unrelated unknown mandatory requirement continues to fail with the flag.
- The callback reaches both normal and resolution-fallback validation paths.
- A custom-schema validation followed by a default validation does not leak support.
- The complete test, lint, and type-check suite remains green.
