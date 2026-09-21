# Architecture and boundaries

The public `validate()` function orchestrates independent source, CWL, package
and metadata checks. It returns a Report even for malformed packages. Models and
rule implementation live in this project; source loading and metadata types are
reused from cwl-loader and transpiler-mate-api. There is no runtime or plugin
registration dependency and no modification to the existing plugin context.

The small metadata normalizer works from original application-level fields,
following the runtime's PyLD expansion semantics. It does not import the runtime's
strict context resolver or its private metadata-preservation attributes. The
same public SoftwareApplication model defines compatibility; this project adds
only explicitly identified quality/migration rules.

Source mapping is conservative. Root and referenced standalone/packed source
processes can be located when their original IDs match uniquely. Inline processes,
transformed identifiers and imported declarations may lack source locations;
these cases never acquire invented offsets. Shared-loader limitations are
reported as blocked assessment when cwltool accepts the document. Dependency
reporting is partial, as described in the report itself.

cwltool validates the original source URI rather than a relocated temporary YAML
copy. Loading and validation perform separate reads; concurrent source changes
are not snapshot-isolated. Use immutable CI checkouts for reproducible reports.
The library performs synchronous inspection. Callers requiring cancellation or
hard resource/time limits should invoke the CLI in a managed subprocess.
HTTP root reads have a timeout; nested loader/parser fetch behavior belongs to
those libraries. No offline guarantee or arbitrary remote-source authentication
interface is provided in this version. OCI sources are not supported.

Separate concerns remain separate: assertions-mate evaluates supplied job inputs,
Trivy scans containers/SBOMs, runners execute workflows, dataset validators inspect
STAC/COG outputs, ORAS publishes OCI artifacts, and Transpiler-Mate generates
publication artifacts. None of those operations is performed by this validator.
