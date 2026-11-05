# Built-in Dask Gateway Schema Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate Calrissian's `DaskGatewayRequirement` when the operator supplies `--enable-dask-gateway`, without adding a Calrissian runtime dependency or generic plugin framework.

**Architecture:** Bundle the trusted schema and a narrowly scoped registration callback inside `eoap_validator`. Thread that callback through all cwltool validation routes and serialize cwltool calls to contain its process-global schema state; the CLI selects the callback with one boolean flag.

**Tech Stack:** Python 3.10+, Click, cwltool, ruamel.yaml, pytest

**Spec:** `docs/superpowers/specs/2026-11-05-dask-gateway-schema-design.md`

## Global Constraints

- Default validation must continue rejecting every unknown mandatory requirement.
- `--enable-dask-gateway` must not import or depend on Calrissian, Dask, or Kubernetes packages.
- Support is validation-only and must not claim workflow execution capability.
- The schema contract is pinned to Duke-GCB/calrissian commit `771768852f0f69aac84a63d8f2ca62e16a22b36a`.
- cwltool registration and validation must be serialized because schema selection is process-global.

## Review Focus

- A Dask requirement missing a required field must fail rather than merely being recognized.
- A Dask field with an invalid type must fail with the flag enabled.
- An unrelated namespaced mandatory requirement must still fail when Dask support is enabled.
- A default validation after a Dask-enabled validation must not inherit the custom schema.
- The resolution-fallback cwltool call must receive the same callback as the normal path.

---

### Task 1: Built-in schema registration

**Files:**
- Create: `src/eoap_validator/extensions/__init__.py`
- Create: `src/eoap_validator/extensions/dask_gateway.py`
- Create: `src/eoap_validator/extensions/dask_gateway.yaml`
- Create: `tests/test_dask_gateway.py`

**Interfaces:**
- Consumes: cwltool's `use_custom_schema(version, name, text)`, `get_schema(version)`, extension schema resources, and supported-requirements list.
- Produces: `DASK_GATEWAY_REQUIREMENT: str` and `register_dask_schema() -> None`.

- [ ] **Step 1: Add failing unit tests for registration**

Test `register_dask_schema()` with monkeypatched cwltool registration functions. Assert registration for `v1.0`, `v1.1`, and `v1.2`, the fully expanded record name, required fields, and idempotent insertion of the requirement URI.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `uv run pytest tests/test_dask_gateway.py -v`
Expected: FAIL because `eoap_validator.extensions.dask_gateway` does not exist.

- [ ] **Step 3: Add the pinned schema resource and registration implementation**

Implement `register_dask_schema() -> None` in `dask_gateway.py`. Load package resources with `importlib.resources.files`, use the already-declared `ruamel.yaml` dependency for safe load/dump, expand named schema definitions with the schema `$base`, and register all three stable CWL versions.

- [ ] **Step 4: Run the focused test and confirm success**

Run: `uv run pytest tests/test_dask_gateway.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eoap_validator/extensions tests/test_dask_gateway.py
git commit -m "feat: bundle Dask Gateway CWL schema"
```

### Task 2: Engine propagation and state isolation

**Files:**
- Modify: `src/eoap_validator/engine.py:1-330`
- Modify: `tests/test_dask_gateway.py`
- Modify: `tests/test_validation.py:320-350`

**Interfaces:**
- Consumes: `SchemaCallback = Callable[[], None]` and `register_dask_schema()` from Task 1.
- Produces: `validate(..., custom_schema_callback: SchemaCallback | None = None) -> Report` and `validate_cwl(uri: str, custom_schema_callback: SchemaCallback | None = None) -> tuple[bool, str]`.

- [ ] **Step 1: Add failing integration and propagation tests**

Add tests asserting that the issue #11 document fails by default, passes CWL validation with `register_dask_schema`, rejects missing/invalid Dask fields, rejects unrelated extensions, resets to default on a subsequent call, and forwards the callback through `resolution_failure()`.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/test_dask_gateway.py tests/test_validation.py::test_loader_limitation_is_not_invalid_cwl -v`
Expected: FAIL because `validate()` and `validate_cwl()` do not accept the callback.

- [ ] **Step 3: Thread the callback through the engine**

Add `SchemaCallback = Callable[[], None]`, optional keyword parameters on the public and internal functions, and pass `custom_schema_callback` to `cwltool_main`. Cover the entire cwltool call and logger restoration with a module-level `threading.RLock`.

- [ ] **Step 4: Run focused tests and confirm success**

Run: `uv run pytest tests/test_dask_gateway.py tests/test_validation.py::test_loader_limitation_is_not_invalid_cwl -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eoap_validator/engine.py tests/test_dask_gateway.py tests/test_validation.py
git commit -m "feat: support trusted cwl schema callback"
```

### Task 3: Purpose-specific CLI and documentation

**Files:**
- Modify: `src/eoap_validator/cli.py:19-70`
- Modify: `tests/test_dask_gateway.py`
- Modify: `README.md:50-110`
- Modify: `docs/reference/profiles.md:1-20`
- Modify: `NOTICE`

**Interfaces:**
- Consumes: `register_dask_schema() -> None` and `validate(..., custom_schema_callback=...)`.
- Produces: Click flag `--enable-dask-gateway`.

- [ ] **Step 1: Add failing CLI tests**

Assert that the issue document exits `1` without the flag, exits `0` with `--enable-dask-gateway`, and still exits `1` for malformed Dask fields with the flag.

- [ ] **Step 2: Run the CLI tests and confirm failure**

Run: `uv run pytest tests/test_dask_gateway.py -k cli -v`
Expected: FAIL because the option is unknown.

- [ ] **Step 3: Implement the Click flag**

Add `@click.option("--enable-dask-gateway", is_flag=True, ...)`, extend `main()` with `enable_dask_gateway: bool`, and pass the built-in callback only when true.

- [ ] **Step 4: Document behavior and provenance**

Document the command, explicit opt-in, validation-only scope, default rejection, schema origin, and synchronization responsibility. Add the upstream MIT attribution to `NOTICE` if required by the copied schema's license.

- [ ] **Step 5: Run the CLI tests and confirm success**

Run: `uv run pytest tests/test_dask_gateway.py -k cli -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eoap_validator/cli.py tests/test_dask_gateway.py README.md docs/reference/profiles.md NOTICE
git commit -m "feat: add Dask Gateway validation flag"
```

### Task 4: Full verification

**Files:**
- Modify only files needed to correct failures caused by Tasks 1-3.

**Interfaces:**
- Consumes: completed feature.
- Produces: verified branch ready for review.

- [ ] **Step 1: Run formatting and lint checks**

Run the repository's configured formatter and lint commands from `Taskfile.yaml`/`pyproject.toml`; expected: zero errors.

- [ ] **Step 2: Run strict type checking**

Run the repository's configured mypy command; expected: zero errors.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: all tests pass.

- [ ] **Step 4: Run the issue #11 CLI reproducer both ways**

Expected: exit `1` without the flag; exit `0` with `--enable-dask-gateway`, with `CWL.VALIDATE` passed and no blocked package graph.

- [ ] **Step 5: Inspect the final diff and working tree**

Run: `git diff main...HEAD --check` and `git status --short`.
Expected: no whitespace errors and no unintended files.

- [ ] **Step 6: Commit verification-only corrections if any**

```bash
git add <only-corrected-files>
git commit -m "test: complete Dask Gateway validation coverage"
```
