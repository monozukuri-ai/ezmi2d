from __future__ import annotations

from pathlib import Path

import pytest

import ezmi

FIXTURE = Path(__file__).parents[1] / "data" / "phase5.mi"


def test_phase5_geometry_and_annotations_are_typed_without_losing_values() -> None:
    document = ezmi.read(FIXTURE)

    fillet = document.get(20)
    assert isinstance(fillet, ezmi.Fillet)
    assert fillet.center == ezmi.Vec2(0.0, 0.0)
    assert fillet.start == ezmi.Vec2(1.0, 0.0)
    assert fillet.end == ezmi.Vec2(0.0, 1.0)
    assert fillet.radius == pytest.approx(1.0)

    spline = document.get(21)
    assert isinstance(spline, ezmi.BSpline)
    assert spline.display_values == (3, 0, 1, 1)
    assert spline.property is document.get(1)
    assert spline.prefix_values == (b"3", b"0", b"1", b"1", b"1")
    assert spline.order == 4
    assert spline.degree == 3
    assert spline.parameter_domain == (0.0, 1.0)
    assert spline.control_point_ids == (13, 14, 15, 16)
    assert all(point is not None for point in spline.control_points)
    assert spline.evaluate(0.0) == ezmi.Vec2(0.0, 0.0)
    assert spline.evaluate(0.5) == ezmi.Vec2(0.5, 0.75)
    assert spline.evaluate(1.0) == ezmi.Vec2(1.0, 0.0)
    assert tuple(sample.point_id for sample in spline.samples) == (13, 16)
    with pytest.raises(ValueError, match="outside"):
        spline.evaluate(2.0)

    assert tuple(type(entity) for entity in document.annotations) == (
        ezmi.DimensionTolerance,
        ezmi.Leader,
        ezmi.Hatch,
        ezmi.Dimension,
        ezmi.Symbol,
    )
    assert document.dimension_tolerances[0].values == (
        b"7",
        b"0.001",
        b"0.0005",
        b"3",
        b"0.9990",
        b"0.9985",
        b"12",
        b"8",
    )
    assert document.dimensions[0].mi_type == "DANG"
    assert document.leaders[0].raw_record.record_type == "LED"
    assert document.hatches[0].raw_record.record_type == "HAT"
    assert document.symbols[0].raw_record.record_type == "SYML"
    assert tuple(entity.id for entity in document.query_annotations("DIMENSION")) == (31,)
    assert tuple(entity.id for entity in document.query_annotations("LEADER, SYMBOL")) == (32, 34)
    assert tuple(entity.id for entity in document.query("FILLET SPLINE")) == (20, 21)
    assert document.query("ARC") == ()
    assert document.parts[0].query() == (fillet, spline)
    assert {entity.id for entity in document.parts[1].annotations} == {31, 32, 33, 34}
    assert tuple(entity.id for entity in document.parts[1].query_annotations("HATCH")) == (33,)


def test_nested_shared_parts_and_multiple_sheets_are_resolved() -> None:
    document = ezmi.read(FIXTURE)

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
    ],
)
def test_malformed_phase5_record_is_retained_as_raw_unsupported(
    mi_type: str, entity_id: int
) -> None:
    data = FIXTURE.read_bytes()
    scan = ezmi.scan(data)
    record = next(
        record
        for record in scan.records_of_type(mi_type)
        if record.payload.splitlines()[1] == str(entity_id).encode()
    )
    replacement = f"{mi_type}\n{entity_id}\n|~\n".encode()
    malformed = data[: record.span.offset] + replacement + data[record.span.end_offset :]

    document = ezmi.read(malformed)
    entity = document.get(entity_id)
    assert isinstance(entity, ezmi.UnsupportedEntity)
    assert entity.mi_type == mi_type
    assert entity.raw_record.payload == f"{mi_type}\n{entity_id}\n".encode()
    assert "MI_INVALID_ENTITY_RECORD" in {diagnostic.code for diagnostic in document.diagnostics}
