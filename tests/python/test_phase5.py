from __future__ import annotations

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
        b"8",
    )
    tolerance = document.dimension_tolerances[0]
    assert tolerance.upper_text == "0.9990"
    assert tolerance.lower_text == "0.9985"
    assert isinstance(tolerance.text_style, ezmi2d.DimensionTextFormatProperty)
    assert tolerance.horizontal_alignment == "center"
    assert tolerance.vertical_alignment == "upper"
    assert document.dimensions[0].mi_type == "DANG"
    dimension = document.dimensions[0]
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
