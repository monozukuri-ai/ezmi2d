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

for occurrence in drawing.iter_instances():
    print(occurrence.path, occurrence.part.name, occurrence.world_transform)

for dimension in drawing.dimensions:
    print(dimension.measurement, dimension.formatted_text, dimension.text_position)

for hatch in drawing.hatches:
    print(hatch.pattern, hatch.boundary_loops)
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
ezmi2d.draw(drawing, ax=ax, expand_instances=True)
ax.legend()
fig.savefig("drawing.png", dpi=160)
```

`ezmi2d.draw(Document)` renders every decoded part definition once by default;
pass `expand_instances=True` to traverse nested/shared instances and apply their
transforms, or pass one part to inspect its definition. This is a semantic
diagnostic preview, not a style-faithful MI renderer. `Arc.ccw` is `True` for
the corpus-verified orientation code `0`; unverified codes are `None` and are
skipped with a warning rather than guessed.

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
- De Boor evaluation for `BSPL`, including rational weights when a verified layout records them
- typed dimension (`DANG`, `DCHMF`, `DDIA`, `DRAD`, `DSGL`) references, measurement,
  formatted text, placement, DDA/DTF style, and linked `DTV` tolerances
- drawable `LED` vertices, `SYML` components, and associative `HAT` patterns/boundaries through
  typed `COC`, `PFA`, and `HAPP` records
- typed `Affine2D`, nested/shared `ASSE` occurrence traversal, composed child-to-parent transforms,
  multi-sheet instances, root parts, and `DOCU_SHEET` links
- strict UTF-8, Shift_JIS/CP932, and HP Roman-8 text decoding with explicit override support
- typed `PSTAT`, `ASSP`, `DTA`, `DTF`, `DDA`, `DLA`, `DAF`, and `HAPP` property models,
  while retaining unverified numeric enumerations in source order
- stable diagnostics for duplicate IDs, bad records, dangling pointers, wrong pointer types,
  table-of-contents mismatch, and Phase 1 structural problems
- `UnsupportedEntity` fallback with its original `RawRecord`; no addressable record is silently
  discarded merely because its semantic decoder is unavailable
- bounded line, section, and `|~` scanning with read-only access to every logical MI byte range
- streaming gzip decompression with container-size, expanded-size, ratio, truncation, checksum,
  trailing-data, and concatenated-member guards

Graphic source semantics are exposed as `color`, `linetype`, `lineweight`, resolved property
tables, and `LAYER:` attributes. Legacy `display_values` remains a compatibility tuple whose
fourth value is the property count, not visibility. The modern extra header value is retained as
`visibility_value`; `visibility` stays `None` until that code is independently verified.
ARC/FIL retain raw `orientation` and separately expose
`ccw: bool | None`; an unknown code is never converted to `False`.
Modern variable-prefix B-splines expose `display_values=None` and retain that
prefix as `prefix_values` instead of guessing a style layout. `closed`,
`periodic`, `rational`, and `weights` are presence-aware; the currently verified
layouts do not establish those meanings and therefore return `None`, distinct
from an explicitly recorded `False`.
For `TEX`, the serialized 3x3 transform, translation, rotation, width factor, mirror state,
alignment, primary/alternate fonts, line spacing, and multiline content are named. Every post-ID
field remains available through `values`. Dimension and annotation layouts are named only where
the product corpus has a self-consistent reference or coordinate role; remaining fields,
B-spline prefixes, and assembly relationship values stay lossless bytes. Writers are not
implemented. gzip-wrapped product-generated compressed MI is supported
by content signature. zlib-wrapper, ZIP, UNIX `compress`, and UNIX `pack`
signatures are recognized and rejected as unsupported instead of being decoded
by assumption. The available genuine sample is a compressed 2D MI member
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
Its 853 lines, 187 arcs, 88 B-splines, 76 circles, 57 texts, 88 typed annotations,
11 hatch contours, 9 hatch associations, 25-part hierarchy, and sheet association produce
identical semantic models and diagnostics from compressed and expanded input. All 46 dimensions
resolve their source geometry and point references; all 16 symbols resolve three graphic
components. One COC member is a retained unsupported `PLN` record.

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
