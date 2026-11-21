from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

import ezmi2d

FIXTURE = Path(__file__).parents[1] / "data" / "phase5.mi"


def test_phase5_geometry_and_annotations_are_typed_without_losing_values() -> None:
    document = ezmi2d.read(FIXTURE)

    fillet = document.get(20)
    assert isinstance(fillet, ezmi2d.Fillet)
    assert fillet.center == ezmi2d.Vec2(0.0, 0.0)
    assert fillet.start == ezmi2d.Vec2(1.0, 0.0)
    assert fillet.end == ezmi2d.Vec2(0.0, 1.0)
    assert fillet.radius == pytest.approx(1.0)
    assert fillet.ccw is True

    spline = document.get(21)
    assert isinstance(spline, ezmi2d.BSpline)
    assert spline.display_values == (3, 0, 1, 1)
    assert spline.property is document.get(1)
    assert spline.prefix_values == (b"3", b"0", b"1", b"1", b"1")
    assert spline.order == 4
    assert spline.degree == 3
    assert spline.parameter_domain == (0.0, 1.0)
    assert spline.closed is None
    assert spline.periodic is None
    assert spline.rational is None
    assert spline.weights is None
    assert spline.control_point_ids == (13, 14, 15, 16)
    assert all(point is not None for point in spline.control_points)
    assert spline.evaluate(0.0) == ezmi2d.Vec2(0.0, 0.0)
    assert spline.evaluate(0.5) == ezmi2d.Vec2(0.5, 0.75)
    assert spline.evaluate(1.0) == ezmi2d.Vec2(1.0, 0.0)
    rational = replace(spline, rational=True, weights=(1.0, 1.0, 1.0, 1.0))
    assert rational.evaluate(0.5) == spline.evaluate(0.5)
    explicit_false = replace(spline, rational=False)
    assert explicit_false.rational is False
    assert spline.rational is None
    assert tuple(sample.point_id for sample in spline.samples) == (13, 16)
    with pytest.raises(ValueError, match="outside"):
        spline.evaluate(2.0)

    assert tuple(type(entity) for entity in document.annotations) == (
        ezmi2d.DimensionTolerance,
        ezmi2d.Leader,
        ezmi2d.Hatch,
        ezmi2d.Dimension,
        ezmi2d.Symbol,
    )
    assert document.dimension_tolerances[0].values == (
        b"7",
        b"0.001",
        b"0.0005",
        b"3",
        b"0.9990",
        b"0.9985",
        b"8",
        b"17",
    )
    tolerance = document.dimension_tolerances[0]
    assert tolerance.upper_text == "0.9990"
    assert tolerance.lower_text == "0.9985"
    assert isinstance(tolerance.text_style, ezmi2d.DimensionTextFormatProperty)
    # The last field of a DTV is the pointer to the DTA of the tolerance text.
    assert tolerance.text_attribute_id == 17
    assert isinstance(tolerance.text_attribute, ezmi2d.DimensionTextAttributeProperty)
    assert tolerance.text_attribute.size == 0.6
    assert tolerance.text_attribute.relative_size is True
    assert tolerance.alignment == 17  # deprecated name of the same field
    assert document.dimensions[0].mi_type == "DANG"
    dimension = document.dimensions[0]
    # The main text names its DTA between the DTF pointer and the measurement; the
    # text position is followed by the extent of the text box along and across the text.
    assert dimension.text_attribute_id == 9
    assert isinstance(dimension.text_attribute, ezmi2d.DimensionTextAttributeProperty)
    assert dimension.text_attribute.size == 0.2
    assert dimension.text_attribute.relative_size is False
    assert dimension.text_attribute.font_name == "hp_block_v"
    assert dimension.text_height == 0.2
    assert dimension.text_extent == ezmi2d.Vec2(0.4, 0.0)
    assert dimension.text_up_extent == ezmi2d.Vec2(0.0, 0.2)
    assert dimension.text_rotation == 0.0
    # A relative size is a factor of the main text of the dimension.
    assert tolerance.text_height() is None
    assert tolerance.text_height(dimension.text_height) == pytest.approx(0.12)
    assert dimension.reference_geometry_ids == (20, 20)
    assert all(value is fillet for value in dimension.reference_geometries)
    assert dimension.reference_point_ids == (10, 11)
    assert all(value is not None for value in dimension.reference_points)
    assert dimension.text_position == ezmi2d.Vec2(0.5, 0.5)
    assert dimension.measurement == pytest.approx(1.5707963267948966)
    assert dimension.formatted_text == "90"

    leader = document.leaders[0]
    assert leader.vertices == (ezmi2d.Vec2(0.0, 0.0), ezmi2d.Vec2(1.0, 0.0))
    assert leader.arrow_type == 1
    assert leader.arrow_size == 1.0

    contour = document.contours[0]
    assert contour.closed is True
    assert contour.component_ids == (20,)
    assert contour.components == (fillet,)
    hatch = document.hatches[0]
    assert hatch.boundary_loop_ids == (35,)
    assert hatch.boundary_loops == (contour,)
    assert isinstance(hatch.pattern, ezmi2d.HatchPatternProperty)
    assert hatch.pattern.lines == (
        ezmi2d.HatchPatternLine(offset=0.0, distance=1.0, angle=0.0, color=3, linetype=0),
    )
    association = document.hatch_associations[0]
    assert association.hatch is hatch
    assert association.outer_loop is contour
    assert association.inner_loops == ()

    symbol = document.symbols[0]
    assert symbol.component_ids == (20, 21, 20)
    assert all(value is not None for value in symbol.components)
    assert tuple(entity.id for entity in document.query_annotations("DIMENSION")) == (31,)
    assert tuple(entity.id for entity in document.query_annotations("LEADER, SYMBOL")) == (32, 34)
    assert tuple(entity.id for entity in document.query("FILLET SPLINE")) == (20, 21)
    assert document.query("ARC") == ()
    assert document.parts[0].query() == (fillet, spline)
    assert {entity.id for entity in document.parts[1].annotations} == {31, 32, 33, 34}
    assert tuple(entity.id for entity in document.parts[1].query_annotations("HATCH")) == (33,)


def test_nested_shared_parts_and_multiple_sheets_are_resolved() -> None:
    document = ezmi2d.read(FIXTURE)

    leaf, sheet_a, sheet_b, drawing = document.parts
    assert document.top_part is drawing
    assert document.modelspace() is drawing
    assert document.root_parts == (drawing,)
    assert document.sheets == (sheet_a, sheet_b)
    assert document.child_parts(drawing) == (sheet_a, sheet_b)
    assert document.child_parts(sheet_a) == (leaf,)
    assert document.child_parts(sheet_b) == (leaf,)
    assert document.parent_parts(leaf) == (sheet_a, sheet_b)
    assert leaf.parent_part_indices == (1, 2)

    assert drawing.assembly is document.get(6)
    assert document.part_for(drawing.assembly) is drawing
    assert tuple(instance.target_part_index for instance in drawing.instances) == (1, 2)
    assert all(instance.is_sheet for instance in drawing.instances)
    assert drawing.instances[1].transform_values == (
        1.0,
        0.0,
        10.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )
    assert sheet_a.instances[0].target_part_index == leaf.index
    assert sheet_b.instances[0].target_part_index == leaf.index

    transform = drawing.instances[1].to_affine2d()
    assert transform == ezmi2d.Affine2D(
        a=1.0,
        b=0.0,
        c=0.0,
        d=1.0,
        tx=10.0,
        ty=0.0,
    )
    assert transform.to_transform_values() == drawing.instances[1].transform_values

    occurrences = tuple(document.iter_instances())
    assert tuple(occurrence.part.index for occurrence in occurrences) == (1, 0, 2, 0)
    assert tuple(occurrence.world_transform.tx for occurrence in occurrences) == (
        0.0,
        0.0,
        10.0,
        10.0,
    )
    assert tuple(occurrence.part.index for occurrence in document.sheet_instances) == (1, 2)
    assert len({occurrence.path for occurrence in occurrences}) == 4

    placed = tuple(document.iter_placed_graphics())
    assert tuple(item.entity.mi_type for item in placed) == ("FIL", "BSPL", "FIL", "BSPL")
    assert tuple(item.world_transform.tx for item in placed) == (0.0, 0.0, 10.0, 10.0)


def test_affine_composition_applies_child_before_parent() -> None:
    parent = ezmi2d.Affine2D(a=0.0, b=1.0, c=-1.0, d=0.0, tx=10.0, ty=20.0)
    child = ezmi2d.Affine2D(a=1.0, b=0.0, c=0.0, d=1.0, tx=2.0, ty=3.0)
    point = ezmi2d.Vec2(4.0, 5.0)

    world = parent.compose(child)
    assert world.transform_point(point) == parent.transform_point(child.transform_point(point))
    assert world.inverse().transform_point(world.transform_point(point)).distance_to(point) < 1e-12

    with pytest.raises(ValueError, match="not affine"):
        ezmi2d.Affine2D.from_transform_values((1.0, 0.0, 0.0) * 3)


@pytest.mark.parametrize(
    ("mi_type", "entity_id"),
    [
        ("ASSE", 3),
        ("FIL", 20),
        ("BSPL", 21),
        ("DTV", 30),
        ("DANG", 31),
        ("LED", 32),
        ("HAT", 33),
        ("SYML", 34),
        ("COC", 35),
        ("PFA", 36),
    ],
)
def test_malformed_phase5_record_is_retained_as_raw_unsupported(
    mi_type: str, entity_id: int
) -> None:
    data = FIXTURE.read_bytes()
    scan = ezmi2d.scan(data)
    record = next(
        record
        for record in scan.records_of_type(mi_type)
        if record.payload.splitlines()[1] == str(entity_id).encode()
    )
    replacement = f"{mi_type}\n{entity_id}\n|~\n".encode()
    malformed = data[: record.span.offset] + replacement + data[record.span.end_offset :]

    document = ezmi2d.read(malformed)
    entity = document.get(entity_id)
    assert isinstance(entity, ezmi2d.UnsupportedEntity)
    assert entity.mi_type == mi_type
    assert entity.raw_record.payload == f"{mi_type}\n{entity_id}\n".encode()
    assert "MI_INVALID_ENTITY_RECORD" in {diagnostic.code for diagnostic in document.diagnostics}


def _xy(point: ezmi2d.Vec2) -> tuple[float, float]:
    return (point.x, point.y)


def test_dimension_graphics_are_read_from_the_fields_after_the_text() -> None:
    document = ezmi2d.readfile(FIXTURE)
    dimension = document.dimensions[0]
    graphics = dimension.graphics
    assert isinstance(graphics, ezmi2d.DimensionGraphics)

    # Every coordinate is stored relative to the text position (0.5, 0.5).
    assert _xy(graphics.text_origin) == pytest.approx((0.3, 0.4))
    assert graphics.text_flag_value == 0

    # The tolerance: the DTV with the texts and where its two texts start.
    placement = graphics.tolerance
    assert isinstance(placement, ezmi2d.DimensionTolerancePlacement)
    assert placement.layout_value == 2
    assert placement.replaces_main_text is False
    assert placement.tolerance is document.dimension_tolerances[0]
    assert _xy(placement.upper_origin) == pytest.approx((0.55, 0.52))
    assert _xy(placement.lower_origin) == pytest.approx((0.55, 0.34))

    # Two terminators; the second one is stored without being drawn.
    first, second = graphics.arrows
    assert (first.display_value, first.visible, first.style_id) == (1, True, 18)
    assert _xy(first.tip) == pytest.approx((1.0, 0.0))
    assert first.angle == pytest.approx(math.pi / 2.0)
    assert (second.display_value, second.visible) == (0, False)
    assert _xy(second.tip) == pytest.approx((0.0, 1.0))
    style = first.style
    assert isinstance(style, ezmi2d.DimensionArrowProperty)
    assert (style.shape_value, style.filling_value, style.relative_size) == (1, 0, False)
    assert style.length() == 0.2
    assert style.width() == 0.052
    # The arrowhead points away from its body: the far end is 0.2 along the angle.
    corner, tip, other = first.outline()
    assert tip == first.tip
    assert (corner.x, corner.y) == pytest.approx((1.0 - 0.026, 0.2))
    assert (other.x, other.y) == pytest.approx((1.0 + 0.026, 0.2))

    assert graphics.line_style_id == 19
    assert isinstance(graphics.line_style, ezmi2d.DimensionLineAttributeProperty)
    assert graphics.lines == ()
    assert all(isinstance(line, ezmi2d.DimensionSegment) for line in graphics.extension_lines)
    assert [(*_xy(line.start), *_xy(line.end)) for line in graphics.extension_lines] == [
        pytest.approx(expected)
        for expected in (
            (1.0, 0.0, 1.1, 0.0),
            (0.0, 1.0, 0.0, 1.1),
            (0.8, 0.0, 1.0, 0.0),
            (0.0, 0.8, 0.0, 1.0),
        )
    ]
    # The arc of the angle in two pieces around the text, counterclockwise.
    assert len(graphics.arcs) == 2
    for arc in graphics.arcs:
        assert _xy(arc.center) == pytest.approx((0.0, 0.0))
        assert arc.radius == pytest.approx(1.0)
        assert arc.center.distance_to(arc.end) == pytest.approx(1.0)
        assert arc.sweep == pytest.approx(math.radians(30.0))
    assert graphics.arcs[0].start == first.tip
    assert graphics.arcs[1].end == second.tip

    prefix, subfix = graphics.text_parts
    assert (prefix.slot, prefix.role, prefix.text) == (1, "prefix", "ca.")
    assert _xy(prefix.origin) == pytest.approx((0.05, 0.4))
    assert prefix.text_attribute_id == 9
    assert prefix.text_height() == 0.2
    assert (subfix.slot, subfix.role, subfix.text) == (4, "subfix", "(TYP)")
    assert _xy(subfix.origin) == pytest.approx((0.3, 0.16))
    # A relative size is a factor of the main text of the dimension.
    assert subfix.text_height() is None
    assert subfix.text_height(dimension.text_height) == pytest.approx(0.12)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # one field more than the layout
        ("(TYP)\n-0.2\n-0.34\n17\n|~", "(TYP)\n-0.2\n-0.34\n17\n0\n|~"),
        # a field that is 0 in every record that was read
        ("0.05\n-0.16\n0\n2\n0\n1\n18\n", "0.05\n-0.16\n1\n2\n0\n1\n18\n"),
        # a count that reaches past the end of the record
        ("\n19\n0\n4\n0\n0.5\n", "\n19\n0\n400\n0\n0.5\n"),
        # a number where a count belongs
        ("\n19\n0\n4\n0\n0.5\n", "\n19\n0.5\n4\n0\n0.5\n"),
    ],
)
def test_dimension_record_that_does_not_follow_the_layout_has_no_graphics(
    tmp_path: Path, old: str, new: str
) -> None:
    source = FIXTURE.read_text(encoding="ascii")
    assert source.count(old) == 1
    path = tmp_path / "other-layout.mi"
    path.write_text(source.replace(old, new), encoding="ascii")

    plain = ezmi2d.readfile(FIXTURE).dimensions[0]
    dimension = ezmi2d.readfile(path).dimensions[0]

    # The rest of the dimension is read as before.
    assert dimension.graphics is None
    assert dimension.text_position == plain.text_position
    assert dimension.text_height == plain.text_height
    assert dimension.formatted_text == plain.formatted_text
    assert dimension.measurement == plain.measurement


@pytest.mark.parametrize(
    ("stored", "drawn"),
    [
        # MI 3.40 (UTF-8): U+E000 plus the code of the symbol font
        ("60\ue030", "60\u00b0"),
        (" \ue031", " \u2300"),
        ("\ue0320.01\ue030", "\u00b10.01\u00b0"),
        # older files: the code between SO and SI
        ("12\x0e0\x0f30\x0e3\x0f15\x0e4\x0f", "12\u00b030'15\""),
        ("\x0e2\x0f0.05", "\u00b10.05"),
        ("\x0e01\x0f", "\u00b0\u2300"),
        # a code that is not known stays, and so does an escape with one in it
        ("5\ue041", "5\ue041"),
        ("5\x0eA\x0f", "5\x0eA\x0f"),
        ("5\x0e0A\x0f", "5\x0e0A\x0f"),
        ("plain R 12.5", "plain R 12.5"),
        ("", ""),
    ],
)
def test_symbol_font_codes_become_the_characters_they_draw(stored: str, drawn: str) -> None:
    assert ezmi2d.replace_symbol_codes(stored) == drawn


def test_pixmap_section_is_not_an_addressable_entity(tmp_path: Path) -> None:
    # MI 2.40 through 2.80 files carry a preview pixmap in section #~31, between the
    # global section and the properties. The field after ``PXMAP`` is 1 and is not an
    # entity ID: read as one it shadowed the first property (ID 1).
    source = FIXTURE.read_text(encoding="ascii")
    assert source.count("#~41\n") == 1
    pixmap = "#~31\nPXMAP\n1\n-1\n2\n2\n8\n0\n0123\n4567\n|~\n"
    path = tmp_path / "pixmap.mi"
    path.write_text(source.replace("#~41\n", pixmap + "#~41\n"), encoding="ascii")

    plain = ezmi2d.readfile(FIXTURE)
    document = ezmi2d.readfile(path)

    assert [
        record.record_type for record in document.raw.records if record.section_number == 31
    ] == ["PXMAP"]
    assert all(entity.mi_type != "PXMAP" for entity in document.all_entities)
    assert len(document.all_entities) == len(plain.all_entities)
    codes = {diagnostic.code for diagnostic in document.diagnostics}
    assert "MI_DUPLICATE_ENTITY_ID" not in codes
    assert codes == {diagnostic.code for diagnostic in plain.diagnostics}
    # The first property is still the part status the assemblies point to.
    first = document.entitydb[1]
    assert isinstance(first, ezmi2d.PartStatusProperty)
