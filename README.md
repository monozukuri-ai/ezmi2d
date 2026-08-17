# ezmi2d

`ezmi2d` is an experimental reader for the line-oriented MI drawing format used
by HP ME10 and PTC Creo Elements/Direct Drafting. Its parser and reference
resolver are written in Rust and exposed to Python through PyO3.

The public API provides typed geometry, annotations, and part structure while retaining the
complete, byte-preserving raw scan:

```python
import ezmi2d

drawing = ezmi2d.read("drawing.mi")
modelspace = drawing.modelspace()

print(drawing.version, drawing.units, drawing.extents)
print(drawing.encoding, drawing.encoding_source)

for entity in modelspace.query("LIN ARC CIR"):
    print(entity.id, entity.mi_type, entity.property_id)

line = drawing.entitydb[10]
if isinstance(line, ezmi2d.Line):
    print(line.start, line.end)

for text in modelspace.query("TEXT"):
    print(text.text, text.origin, text.height, text.font_name)

for spline in drawing.query("FIL BSPL"):
    print(spline.id, spline.mi_type)

for sheet in drawing.sheets:
    print(sheet.name, sheet.child_part_indices)
```

## Matplotlib preview

Install the optional plotting dependency and render a decoded fixture to PNG:

```console
pip install "ezmi2d[plot]"
python examples/plot_mi.py tests/data/geometry.mi -o geometry.png
```

The plotting helper can also be embedded directly:

```python
import matplotlib.pyplot as plt
import ezmi2d

drawing = ezmi2d.read("drawing.mi")
fig, ax = plt.subplots()
ezmi2d.draw(drawing, ax=ax)
ax.legend()
fig.savefig("drawing.png", dpi=160)
```

`ezmi2d.draw(Document)` renders every decoded part definition once; use
`ezmi2d.draw(drawing.parts[index])` to inspect one part. This is a semantic
diagnostic preview, not a style-faithful MI renderer: unknown display fields,
typed-but-opaque annotations, and assembly instance transforms are not applied.
The current sample corpus verifies `orientation=0` arcs as counter-clockwise;
other orientation values are skipped with a warning rather than guessed.

`read()` accepts a path or bytes-like object, including the verified
gzip-compressed MI envelope. Point and property pointers are
resolved after all records have been decoded, so forward references work and
dangling or wrong-type references produce source-located diagnostics rather
than aborting the whole drawing.

Text is decoded strictly. The reader checks an explicit `encoding=` override,
a UTF-8 BOM, MI 3.20-or-newer version metadata, and a `#~1` `ENCODING:`
declaration before conservatively inspecting known text fields in older files.
Supported canonical encodings are `utf-8`, `shift_jis` (including `cp932` and
`windows-31j` aliases), and `hp-roman8`:

```python
drawing = ezmi2d.read("legacy-japanese.mi", encoding="cp932")
text = drawing.query("TEX")[0]
print(text.text, text.text_bytes, text.content_value.encoding)
```

Invalid or undecidable text is never decoded with replacement characters.
`TextValue.text` remains `None`, `TextValue.raw_bytes` retains the source, and a
source-located diagnostic identifies the bad byte.

The lower-level lossless scanner remains available when inspecting unsupported
records or developing new entity decoders:

```python
scan = ezmi2d.scan("drawing.mi")
for record in scan.records:
    print(record.section_number, record.record_type, record.raw_bytes)

packed = ezmi2d.scan("drawing.bi")
print(packed.format.compression, packed.container_size, packed.source_size)
assert packed.container_bytes != packed.source_bytes
```

For compressed inputs, every source span addresses the decompressed logical MI
stream exposed as `source_bytes`. The exact caller input remains available as
`container_bytes`. Streaming decompression is bounded independently by
`ScanLimits.max_file_size`, `max_decompressed_size`, and
`max_compression_ratio`.

The CLI emits a raw structural summary or JSON suitable for corpus inspection:

```console
ezmi2d inspect drawing.mi
ezmi2d inspect drawing.mi --json --records
```

## Current scope

- legacy MI 2.10 global metadata, drawing extents, units, and serialized transform values
- `#~6` part ownership and an ezdxf-style `modelspace()`, `query()`, and `entitydb`
- typed `P`, `LIN`, `ARC`, `FIL`, `BSPL`, `CIR`, and `TEX` entities; point references are resolved
- De Boor evaluation for non-rational `BSPL`, including modern variable-prefix records
- typed dimension (`DANG`, `DCHMF`, `DDIA`, `DRAD`, `DSGL`), `DTV`, `LED`, `HAT`, and `SYML`
- nested/shared `ASSE` instances, serialized 3x3 transforms, root parts, and `DOCU_SHEET` links
- strict UTF-8, Shift_JIS/CP932, and HP Roman-8 text decoding with explicit override support
- minimally decoded `PSTAT`, `ASSP`, dimension/hatch properties, and `ASSE` records
- stable diagnostics for duplicate IDs, bad records, dangling pointers, wrong pointer types,
  table-of-contents mismatch, and Phase 1 structural problems
- `UnsupportedEntity` fallback with its original `RawRecord`; no addressable record is silently
  discarded merely because its semantic decoder is unavailable
- bounded line, section, and `|~` scanning with read-only access to every logical MI byte range
- streaming gzip decompression with container-size, expanded-size, ratio, truncation, checksum,
  trailing-data, and concatenated-member guards

The four common graphic display fields are exposed conservatively as
`display_values`, and the ARC direction field is retained as `orientation`:
their formal names and complete semantics have not yet been established.
Modern variable-prefix B-splines expose `display_values=None` and retain that
prefix as `prefix_values` instead of guessing a style layout.
For `TEX`, only fields validated across the available MI/DXF pairs are named:
the serialized 3x3 transform, its translation as `origin`, font name, two text
size values, height, and content. Every post-ID field remains available through
`values`. Annotation fields, B-spline prefix values, and assembly relationship fields whose
formal names are not verified are likewise exposed as lossless serialized values. Writers are
not implemented. gzip-wrapped product-generated compressed MI is supported
by content signature. zlib-wrapper, ZIP, and historical UNIX-compress variants
remain unsupported. The available genuine sample is a compressed 2D MI member
inside a Creo bundle, not a separately exported standalone `.bi`; compatibility
with every Drafting/ME10 `.bi` generation is therefore not claimed.

See the [Python API reference](docs/api.md),
[MI format research](docs/mi-format-research.md), and
[sample corpus guide](samples/README.md). Third-party drawings are not distributed in Git,
sdists, or wheels.

The opt-in corpus suite currently exercises 19 MI 2.10 drawings containing
10,166 points, 4,030 lines, 1,059 arcs, 353 fillets, 1,196 circles, 6 B-splines,
and 57 text entities. The
paired DXF tests compare line endpoints, arc center/start/end points, circle
centers/radii, drawing extents, and text content/insertion/height to seven
decimal places. Fillets exactly match the additional DXF arcs. Stored B-spline
interpolation points and every vertex of the corresponding DXF polylines are
evaluated against the decoded curves.

It also verifies a product-generated MI 3.40 / UTF-8 compressed member from a
public Creo bundle: 87,506 compressed bytes expand to 393,805 logical bytes.
Its 88 B-splines, 88 typed annotations, 25-part hierarchy, and sheet association
produce identical semantic models and diagnostics from compressed and expanded input.

## Distribution

Release automation builds `cp310-abi3` wheels for Linux x86-64 and ARM64, macOS universal2, and
Windows x64. Artifact-only smoke tests cover Python 3.10 and 3.14, and the sdist is rebuilt and
installed in a clean job. See [docs/releasing.md](docs/releasing.md) for the complete release gates
and Trusted Publishing setup.

## Development

```console
uv sync --locked --extra dev
uv run maturin develop
uv run pytest
cargo test --workspace
uv run python benchmarks/benchmark_pipeline.py tests/data --warmup 0 --repeat 1 \
  --json-output /tmp/ezmi2d-benchmark.json --markdown-output /tmp/ezmi2d-benchmark.md
```

Parser fuzzing uses nightly Rust and `cargo-fuzz`:

```console
cargo +nightly fuzz run raw_scan
cargo +nightly fuzz run semantic_read
```

To fetch and run the separately licensed corpus comparison:

```console
./scripts/fetch_external_samples.sh
uv sync --locked --extra dev --extra corpus
uv run --extra corpus pytest tests/python/test_external_corpus.py
```
