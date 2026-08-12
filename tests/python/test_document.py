from __future__ import annotations

import gzip
import math
from pathlib import Path

import pytest

import ezmi

FIXTURE = Path(__file__).parents[1] / "data" / "geometry.mi"


def test_read_builds_typed_geometry_and_resolves_references() -> None:
    document = ezmi.read(FIXTURE)

    assert document.version == "2.10"
    assert document.units == "mm"
    assert document.header is document.global_info
    assert document.global_info is not None
    assert document.global_info.drawing_name == "geometry"
    assert document.global_info.drawing_name_bytes == b"geometry"
    assert document.global_info.dimension == "2D"
    assert document.global_info.paper_size == "A4"
    assert document.global_info.drawing_scale == pytest.approx(1.0)
    assert document.global_info.angle_unit == "RAD"
    assert document.encoding is None
    assert document.encoding_source == "ascii_only"
    assert document.declared_encoding is None
    assert document.extents == ezmi.Bounds2(ezmi.Vec2(0.0, 0.0), ezmi.Vec2(10.0, 10.0))
    assert document.global_info.transform_values == (
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )

    assert len(document.all_entities) == 13
    assert len(document.points) == 6
    assert len(document.entities) == 3
    assert len(document.properties) == 2
    assert len(document.assemblies) == 1
    assert len(document.unsupported_entities) == 1
    assert tuple(document.entitydb) == tuple(range(1, 14))
    assert document.toc_last_entity == 13

    line = document.get(10)
    assert isinstance(line, ezmi.Line)
    assert line.display_values == (3, 0, 1, 1)
    assert line.property_id == 2
    assert line.property is document.get(2)
    assert line.start_id == 4
    assert line.end_id == 5
    assert line.start_point is document.get(4)
    assert line.end_point is document.get(5)
    assert line.start == ezmi.Vec2(0.0, 0.0)
    assert line.end == ezmi.Vec2(10.0, 0.0)
    assert line.raw_record.record_type == "LIN"

    arc = document.get(11)
    assert isinstance(arc, ezmi.Arc)
    assert arc.center == ezmi.Vec2(5.0, 5.0)
    assert arc.start == ezmi.Vec2(10.0, 5.0)
    assert arc.end == ezmi.Vec2(5.0, 10.0)
    assert arc.orientation == 0
    assert arc.radius == pytest.approx(5.0)
    assert arc.start_angle == pytest.approx(0.0)
    assert arc.end_angle == pytest.approx(math.pi / 2.0)

    circle = document.get(12)
    assert isinstance(circle, ezmi.Circle)
    assert circle.center == ezmi.Vec2(5.0, 5.0)
    assert circle.circumference == ezmi.Vec2(8.0, 5.0)
    assert circle.radius == pytest.approx(3.0)


def test_parts_queries_and_unknown_records_remain_accessible() -> None:
    document = ezmi.read(FIXTURE.read_bytes())

    assert len(document.parts) == 1
    assert document.top_part is document.parts[0]
    assert document.modelspace() is document.parts[0]
    assert document.top_part is not None
    assert document.top_part.name == "Top"
    assert document.top_part.name_bytes == b"Top"
    assert tuple(entity.id for entity in document.top_part.source_entities) == tuple(range(4, 14))
    assert tuple(entity.id for entity in document.top_part.points) == tuple(range(4, 10))
    assert tuple(entity.id for entity in document.top_part.entities) == (10, 11, 12)
    assert tuple(entity.id for entity in document.query("LINE, CIRCLE")) == (10, 12)
    assert tuple(entity.id for entity in document.top_part.query("LIN ARC")) == (10, 11)
    assert document.query() == document.entities

    unknown = document.get(13)
    assert isinstance(unknown, ezmi.UnsupportedEntity)
    assert unknown.mi_type == "MYSTERY"
    assert unknown.raw_record.payload == b"MYSTERY\n13\nopaque\n"
    assert document.top_part.unsupported_entities == (unknown,)
    assert [diagnostic.code for diagnostic in document.diagnostics] == ["MI_UNSUPPORTED_ENTITY"]
    assert document.raw.diagnostics == ()

    assert document.query("TEXT") == ()
    with pytest.raises(ValueError, match="unsupported MI entity query type"):
        document.query("DIMENSION")
    with pytest.raises(TypeError):
        document.entitydb[99] = unknown  # type: ignore[index]


def test_dangling_and_wrong_type_references_are_non_fatal() -> None:
    data = FIXTURE.read_bytes()
    original = b"LIN\n10\n3\n0\n1\n1\n2\n4\n5\n|~"
    malformed = b"LIN\n10\n3\n0\n1\n1\n99\n999\n2\n|~"
    assert data.count(original) == 1

    document = ezmi.read(data.replace(original, malformed))
    line = document.get(10)
    assert isinstance(line, ezmi.Line)
    assert line.property_id == 99
    assert line.property is None
    assert line.start_id == 999
    assert line.start is None
    assert line.end_id == 2
    assert line.end is None
    assert {
        "MI_DANGLING_POINT_REFERENCE",
        "MI_DANGLING_PROPERTY_REFERENCE",
        "MI_REFERENCE_TYPE_MISMATCH",
    }.issubset({diagnostic.code for diagnostic in document.diagnostics})


def test_duplicate_ids_are_reported_and_first_definition_wins() -> None:
    data = FIXTURE.read_bytes()
    assert data.count(b"CIR\n12\n") == 1

    document = ezmi.read(data.replace(b"CIR\n12\n", b"CIR\n10\n"))

    assert [entity.id for entity in document.all_entities].count(10) == 2
    assert isinstance(document.entitydb[10], ezmi.Line)
    assert "MI_DUPLICATE_ENTITY_ID" in {diagnostic.code for diagnostic in document.diagnostics}


def test_duplicate_id_does_not_bypass_first_definition_reference_type() -> None:
    data = FIXTURE.read_bytes()
    data = data.replace(b"P\n4\n0\n0\n|~", b"P\n1\n0\n0\n|~")
    data = data.replace(
        b"LIN\n10\n3\n0\n1\n1\n2\n4\n5\n|~",
        b"LIN\n10\n3\n0\n1\n1\n2\n1\n5\n|~",
    )

    document = ezmi.read(data)
    line = document.get(10)
    assert isinstance(document.entitydb[1], ezmi.Property)
    assert isinstance(line, ezmi.Line)
    assert line.start_id == 1
    assert line.start is None
    assert {"MI_DUPLICATE_ENTITY_ID", "MI_REFERENCE_TYPE_MISMATCH"}.issubset(
        {diagnostic.code for diagnostic in document.diagnostics}
    )


def test_invalid_known_record_is_retained_as_unsupported() -> None:
    data = FIXTURE.read_bytes()
    original = b"P\n4\n0\n0\n|~"
    malformed = b"P\n4\nNaN\n0\n|~"
    assert data.count(original) == 1

    document = ezmi.read(data.replace(original, malformed))

    entity = document.get(4)
    assert isinstance(entity, ezmi.UnsupportedEntity)
    assert entity.mi_type == "P"
    assert entity.raw_record.payload == b"P\n4\nNaN\n0\n"
    codes = {diagnostic.code for diagnostic in document.diagnostics}
    assert "MI_INVALID_ENTITY_RECORD" in codes
    assert "MI_REFERENCE_TYPE_MISMATCH" in codes


def test_readfile_alias_and_limits_match_the_raw_scanner() -> None:
    assert ezmi.readfile(FIXTURE).entitydb.keys() == ezmi.read(FIXTURE).entitydb.keys()
    with pytest.raises(ezmi.MiLimitError, match="record count"):
        ezmi.read(FIXTURE, limits=ezmi.ScanLimits(max_records=1))


def test_gzip_and_plain_inputs_have_the_same_semantic_model() -> None:
    data = FIXTURE.read_bytes()
    compressed = gzip.compress(data, mtime=0)

    plain = ezmi.read(data)
    packed = ezmi.read(compressed)

    assert packed.raw.format.compression == "gzip"
    assert packed.raw.source_bytes == data
    assert packed.raw.container_bytes == compressed
    assert packed.global_info == plain.global_info
    assert packed.encoding_info == plain.encoding_info
    assert packed.toc_last_entity == plain.toc_last_entity
    assert packed.parts == plain.parts
    assert packed.all_entities == plain.all_entities
    assert packed.diagnostics == plain.diagnostics
