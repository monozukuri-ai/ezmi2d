# Python API reference

`ezmi2d` exposes a bounded, lossless raw scanner and a higher-level semantic reader. Both APIs accept
filesystem paths and `bytes`, `bytearray`, or `memoryview` values. Python 3.10 through 3.14 is
supported by the `cp310-abi3` wheels.

## Reading a drawing

```python
import ezmi2d

drawing = ezmi2d.read("drawing.mi")
print(drawing.version, drawing.units, drawing.extents)

for entity in drawing.modelspace().query("LINE ARC FILLET BSPLINE CIRCLE TEXT"):
    print(entity.id, entity.mi_type, entity.raw_record.span)
```

The top-level entry points are:

```python
ezmi2d.detect_format(source) -> MiFormatInfo
ezmi2d.scan(source, *, limits=None) -> RawScan
ezmi2d.scan_records(source, *, limits=None) -> RawScan
ezmi2d.read(source, *, limits=None, encoding=None) -> Document
ezmi2d.readfile(path, *, limits=None, encoding=None) -> Document
```

`scan_records` is an alias of `scan`; `readfile` is the path-oriented alias of `read`. File names and
extensions are not used to identify the format. A path is read at most `max_file_size + 1` bytes, so
the configured bound still applies if a file grows after it is opened.

## Semantic document

`Document` (also exported as `Drawing`) provides:

| Member | Meaning |
|---|---|
| `raw` | Complete `RawScan` backing the semantic model |
| `header`, `global_info` | Verified global metadata or `None` |
| `version`, `units`, `extents` | Common global metadata shortcuts |
| `parts` | All part definitions in source order |
| `top_part`, `modelspace()` | Selected top part; `modelspace()` raises `LookupError` if absent |
| `root_parts`, `sheets` | Bound hierarchy roots and verified `DOCU_SHEET` parts |
| `sheet_instances` | Placed sheet occurrences, preserving duplicate/shared paths |
| `all_entities` | Every addressable typed or unsupported entity in source order |
| `entitydb` | Read-only first-occurrence mapping from ID to entity |
| `points`, `entities`, `texts` | Point and graphic subsets |
| `annotations` | Dimensions, tolerances, leaders, hatches, and symbols |
| `dimensions`, `dimension_tolerances`, `leaders`, `hatches`, `symbols` | Annotation-family subsets |
| `contours`, `hatch_associations` | COC boundary loops and PFA hatch associations |
| `properties`, `assemblies`, `unsupported_entities` | Other semantic subsets |
| `diagnostics` | Raw plus semantic non-fatal observations |

`Document.get(id)` returns an entity or `None`. `part_for(entity)`, `child_parts(part)`, and
`parent_parts(part)` navigate bound ownership without flattening assembly instances.

`iter_part_occurrences()` traverses the top part and every nested instance in
source order. `iter_instances()` omits the root occurrence, while
`iter_placed_graphics()` pairs each graphic definition with its occurrence.
Shared parts are yielded once per path. Each `PartOccurrence` carries
`local_transform`, composed `world_transform`, a typed `path`, and `is_sheet`.
Unbound, cyclic, or non-affine branches raise by default; `strict=False` omits
them without inventing a placement.

### Assembly transform convention

`AssemblyInstance.to_affine2d()` converts the serialized nine values to an
`Affine2D`. The public convention is row-major, column-vector, and
child-to-parent:

```text
| a c tx |   | x |   | a*x + c*y + tx |
| b d ty | * | y | = | b*x + d*y + ty |
| 0 0  1 |   | 1 |   |        1        |
```

`parent.compose(child)` returns `parent ∘ child`, so nested traversal applies
the child-local transform first. `transform_point()`, `transform_vector()`,
`inverse()`, `determinant`, `is_mirrored`, and `to_transform_values()` use the
same convention. A serialized matrix whose final row is not approximately
`(0, 0, 1)` is rejected rather than treated as affine.

The repository fixture verifies translation and nested/shared composition. The
available product MI contains 24 identity transforms only; a non-identity
product MI plus corresponding product DXF/render remains required before this
convention can be claimed as product-corpus verified.

`Document.query()` and `Part.query()` accept comma- or whitespace-separated names. Supported aliases
are `LINE`/`LIN`, `ARC`, `FILLET`/`FIL`, `BSPLINE`/`SPLINE`/`BSPL`, `CIRCLE`/`CIR`, and
`TEXT`/`TEX`; `"*"` selects all graphic entities. `query_annotations()` accepts exact MI names plus
the families `DIMENSION`, `TOLERANCE`, `LEADER`, `HATCH`, and `SYMBOL`. An unknown query name raises
`ValueError` rather than silently returning an empty result.

## Matplotlib diagnostic plotting

Install `ezmi2d[plot]` to make the optional renderer available:

```python
import matplotlib.pyplot as plt
import ezmi2d

drawing = ezmi2d.read("drawing.mi")
fig, ax = plt.subplots()
ezmi2d.draw(
    drawing,
    ax=ax,
    curve_segments=128,
    show_points=False,
    show_text=True,
    expand_instances=True,
)
fig.savefig("drawing.png", dpi=160)
```

`draw()` accepts either a `Document` or one `Part` and returns the Matplotlib
`Axes`. A document draws all directly decoded part definitions once by default;
`expand_instances=True` traverses the assembly graph and applies composed
instance transforms. `LIN`, `ARC`, `FIL`, `BSPL`, `CIR`,
`TEX`, and optionally `P` are displayed with diagnostic colors; MI display
attributes and typed-but-opaque annotations are not rendered. Arc direction
comes from `ccw`; orientation `0` maps to counter-clockwise from the paired
MI/DXF corpus. Unknown orientations and unresolved geometry are skipped with a
`RuntimeWarning`.

## Entity model

Every entity derives from the frozen `MiEntity` data model and retains `id`, `mi_type`,
`raw_record`, and `part_index`.

| MI record | Python type | Decoded contract |
|---|---|---|
| `P` | `Point` | `location` |
| `LIN` | `Line` | resolved start/end point IDs and coordinates |
| `ARC` | `Arc` | resolved center/start/end, radius, normalized angles, raw `orientation`, `ccw` |
| `FIL` | `Fillet` | verified arc-compatible fillet geometry |
| `BSPL` | `BSpline` | order/degree, presence-aware flags/weights, controls, knots, samples, `evaluate()` |
| `CIR` | `Circle` | resolved center/circumference and radius |
| `TEX` | `Text` | 3x3 transform, origin, rotation, width factor, mirror, alignment, fonts, multiline content |
| `DANG`, `DCHMF`, `DDIA`, `DRAD`, `DSGL` | `Dimension` | resolved geometry/point references, text position, measurement, formatted text, DDA/DTF styles, DTA text attribute (`text_attribute`, `text_height`), stored text box (`text_extent`, `text_up_extent`, `text_rotation`), DTV references, the stored drawn form (`graphics`) |
| `DTV` | `DimensionTolerance` | upper/lower values and text, DTF style, DTA text attribute (`text_attribute`, `text_height(main_text_height)`) |
| `LED` | `Leader` | graphic attributes, arrow code/size, ordered 2D vertices and retained elevations |
| `COC` | `Contour` | ordered graphic components, closed flag, raw orientation |
| `HAT` / `PFA` | `Hatch` / `HatchAssociation` | pattern origin/angle/spacing and resolved outer/inner COC loops |
| `SYML` | `Symbol` | three ordered, resolved graphic components |
| `PSTAT`, `ASSP` | specialized property types | part status and strictly decoded associated strings |
| `DTA` | `DimensionTextAttributeProperty` | fonts, `size` (character height, or a factor of the main text when `relative_size` is true); the other numeric values remain ordered values |
| `DTF`, `DDA`, `DLA` | dimension property subclasses | typed numeric tables; unverified enumerations remain ordered values |
| `DAF` | `DimensionArrowProperty` | `shape_value`, `filling_value`, `relative_size`, `length()` and `width()` of a dimension terminator; the numeric table stays in `definition_values` |
| `HAPP` | `HatchPatternProperty` | ordered offset/distance/angle/color/linetype sub-patterns |
| `ASSE` | `Assembly` | property IDs, definition part, child instances, 3x3 transforms |
| other addressable records | `UnsupportedEntity` | ID, ownership, and complete raw record |

Fields whose meaning has not been verified remain `bytes` in `values`, `definition_values`, or
`prefix_values`. Absence is not collapsed into zero: unresolved pointers and unavailable style
headers remain `None`. `BSpline` layout probing is bounded to the first 64 candidate prefix fields;
unknown longer-prefix layouts fall back to `UnsupportedEntity` with an
`MI_INVALID_ENTITY_RECORD` diagnostic.

### The drawn form of a dimension

`Dimension.graphics` is the form the file stores after the formatted text, as a
`DimensionGraphics`, or `None` when those fields do not follow the layout read from
MI 2.40 through 3.40. The file keeps these coordinates relative to the text position;
`ezmi2d` adds the text position, so they are in the coordinate system of the part like
every other entity.

| Attribute | Content |
|---|---|
| `text_origin` | start of the main text: the lower left corner of its first character. Every text runs along `Dimension.text_rotation` |
| `tolerance` | `DimensionTolerancePlacement` or `None`: the `DimensionTolerance` and the starts of its upper and lower text. `layout_value` is 1 (one text after the main text), 2 (an upper and a lower text after it) or 3 (two limits in place of the main text, `replaces_main_text`) |
| `arrows` | `DimensionArrow`: `tip`, `angle` (from the tip along the body, radians), the `DimensionArrowProperty` in `style`, and `visible` (a terminator can be stored without being drawn). `outline(main_text_height)` gives an arrowhead as three points; it is `None` for a shape other than the two arrowheads |
| `lines`, `extension_lines` | `DimensionSegment` (`start`, `end`) pieces of the dimension line and of the extension lines |
| `arcs` | `DimensionArc` (`start`, `end`, `center`, `radius`, `sweep`), counterclockwise from start to end |
| `text_parts` | `DimensionTextPart`: a text beside the main text with its `origin`, DTA `text_attribute`, `text_height(main_text_height)` and `role` (`"prefix"`, `"postfix"`, `"subfix"` for a row below, or `None`) |
| `line_style` | the `DimensionLineAttributeProperty` (DLA) of the lines |
| `text_flag_value` | a stored 0 or 1 whose meaning is not established |

```python
for dimension in drawing.dimensions:
    graphics = dimension.graphics
    if graphics is None:
        continue
    for segment in (*graphics.lines, *graphics.extension_lines):
        print("line", segment.start, segment.end)
    for arrow in graphics.arrows:
        if arrow.visible:
            print("arrowhead", arrow.outline(dimension.text_height))
    print(ezmi2d.replace_symbol_codes(dimension.formatted_text or ""), graphics.text_origin)
```

A dimension text switches to the symbol font by code: U+E000 plus the code in a UTF-8
file, the code between SO (0x0E) and SI (0x0F) in an older one.
`ezmi2d.replace_symbol_codes(text)` replaces the codes 0 through 4 by the degree sign,
the diameter sign, the plus-minus sign, `'` (minutes) and `"` (seconds) and leaves any
other code as it is. `formatted_text` and the other text values are not changed by it.

Every `GraphicEntity` exposes typed `color`, `linetype`, `lineweight`, attached
`property_ids` / resolved `properties`, and layers decoded from `ASSP` values
whose source text starts with `LAYER:`. `display_values` is a compatibility view
of the legacy `(color, linetype, lineweight, property_count)` header and is
`None` for the modern variable-property header. The extra modern integer is
retained as `visibility_value`; `visibility` remains `None` because the available
reference and corpus do not establish that integer's visibility semantics.

## Text encoding

Text is decoded strictly, in this precedence order:

1. explicit `encoding=` passed to `read()`;
2. UTF-8 BOM;
3. MI version 3.20 or newer (UTF-8);
4. `ENCODING:` declaration in section `#~1`;
5. conservative inspection of known text fields in legacy files.

Canonical supported names are `utf-8`, `shift_jis`, and `hp-roman8`; common CP932 and Windows-31J
labels map to `shift_jis`. A decode failure leaves `TextValue.text` as `None`, preserves
`TextValue.raw_bytes`, and emits a source-located diagnostic. No replacement characters are
inserted.

## Lossless raw API

`RawScan` contains all physical `RawLine` objects, logical `RawSection` objects, and framed or
unframed `RawRecord` objects. `SourceSpan` offsets are half-open byte ranges in `source_view`; line
numbers are one-based. The `*_view` properties are read-only `memoryview` slices and the `*_bytes`
properties make explicit copies.

For an uncompressed file, `container_bytes == source_bytes`. For gzip input, `container_bytes`
retains the caller's compressed bytes while `source_bytes` is the logical MI stream addressed by
all spans. `find_sections(number)` and `records_of_type(mi_type)` preserve source order.

## Limits and failures

`ScanLimits` applies to both `scan()` and `read()`:

| Field | Default |
|---|---:|
| `max_file_size` | 1 GiB |
| `max_lines` | 10,000,000 |
| `max_sections` | 100,000 |
| `max_records` | 5,000,000 |
| `max_line_size` | 16 MiB |
| `max_record_size` | 256 MiB |
| `max_decompressed_size` | 1 GiB |
| `max_compression_ratio` | 1,000 |

Use tighter limits for untrusted workloads:

```python
limits = ezmi2d.ScanLimits(
    max_file_size=64 * 1024 * 1024,
    max_decompressed_size=128 * 1024 * 1024,
    max_compression_ratio=100,
)
drawing = ezmi2d.read(uploaded_bytes, limits=limits)
```

Fatal failures use this hierarchy:

- `MiError`: base parser exception;
- `InvalidMiError`: unrecognized input, corrupt/truncated gzip, or invalid gzip envelope;
- `UnsupportedMiError`: a recognized but unsupported compression family;
- `MiLimitError`: a configured resource limit was exceeded.

Path access can additionally raise normal `OSError` subclasses. Structural and semantic problems
that do not prevent bounded scanning are returned as `Diagnostic` values with a stable `code`,
severity, `SourceSpan`, message, and optional suggested action. Callers that require clean drawings
should explicitly reject `error` diagnostics; warnings do not automatically make `read()` fail.

## Format boundary

The reader supports text MI and the corpus-verified single-member gzip envelope. Content signatures
for zlib wrappers, ZIP, UNIX `compress` (`1f 9d`), and UNIX `pack` (`1f 1e`) are recognized, but
those unverified families raise `UnsupportedMiError` instead of being guessed as gzip. Concatenated
gzip members and gzip trailing bytes are rejected as invalid. `.bi` compatibility across all
Drafting/ME10 releases is not claimed. Writing and round-tripping modified documents are outside
the reader API.
