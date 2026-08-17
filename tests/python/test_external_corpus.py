from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import ezmi2d

CORPUS = Path(__file__).parents[2] / "samples" / "external" / "takahiro-soarerdex" / "mi"
DXF_CORPUS = CORPUS.parent / "dxf"
PTC_CORPUS = Path(__file__).parents[2] / "samples" / "external" / "ptc-community-mandrel"
PTC_COMPRESSED_MI = PTC_CORPUS / "compressed" / "am_2d_0.mi"
PTC_LOGICAL_MI = PTC_CORPUS / "mi" / "am_2d_0.mi"


def test_downloaded_legacy_corpus_scans_losslessly() -> None:
    if not CORPUS.is_dir():
        pytest.skip("external MI corpus has not been downloaded")

    files = sorted(path for path in CORPUS.iterdir() if path.is_file())
    assert len(files) == 19

    counts: Counter[str] = Counter()
    for path in files:
        result = ezmi2d.scan(path)
        assert result.format.first_section == 2
        assert result.termination == "file_marker"
        assert result.trailing_bytes == 0
        assert result.newlines.crlf == len(result.lines)
        assert result.newlines.lf == 0
        assert result.source_bytes == path.read_bytes()
        assert result.diagnostics == ()
        counts.update(
            record.record_type for record in result.records if record.record_type is not None
        )

    assert {name: counts[name] for name in ("P", "LIN", "ARC", "CIR", "TEX")} == {
        "P": 10166,
        "LIN": 4030,
        "ARC": 1059,
        "CIR": 1196,
        "TEX": 57,
    }


def test_downloaded_legacy_corpus_decodes_the_phase5_subset() -> None:
    if not CORPUS.is_dir():
        pytest.skip("external MI corpus has not been downloaded")

    files = sorted(path for path in CORPUS.iterdir() if path.is_file())
    assert len(files) == 19

    counts: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    direction_counts: Counter[tuple[str, int, bool | None]] = Counter()
    for path in files:
        document = ezmi2d.read(path)
        assert document.version == "2.10"
        assert document.units == "mm"
        assert len(document.parts) == 1
        assert document.top_part is not None
        assert document.top_part.name == "Top"
        assert document.toc_last_entity == max(entity.id for entity in document.all_entities)
        assert len(document.entitydb) == len(document.all_entities)
        assert all(entity.property is not None for entity in document.entities)
        assert all(_geometry_is_resolved(entity) for entity in document.entities)
        assert document.encoding == "shift_jis"
        assert document.encoding_source == "heuristic"
        assert all(text.text is not None for text in document.texts)
        assert all("\ufffd" not in text.text for text in document.texts if text.text is not None)

        counts.update(entity.mi_type for entity in document.all_entities)
        direction_counts.update(
            (entity.mi_type, entity.orientation, entity.ccw)
            for entity in document.entities
            if isinstance(entity, (ezmi2d.Arc, ezmi2d.Fillet))
        )
        diagnostic_counts.update(diagnostic.code for diagnostic in document.diagnostics)

    assert counts == {
        "P": 10166,
        "PSTAT": 19,
        "ASSP": 19,
        "ASSE": 19,
        "LIN": 4030,
        "ARC": 1059,
        "CIR": 1196,
        "FIL": 353,
        "BSPL": 6,
        "TEX": 57,
    }
    assert direction_counts == {
        ("ARC", 0, True): 1_059,
        ("FIL", 0, True): 353,
    }
    assert diagnostic_counts == {
        "MI_ENCODING_GUESSED": 19,
    }


def test_phase5_geometry_and_text_match_the_paired_dxf_corpus() -> None:
    if not CORPUS.is_dir() or not DXF_CORPUS.is_dir():
        pytest.skip("paired external MI/DXF corpus has not been downloaded")
    ezdxf = pytest.importorskip("ezdxf", reason="install the corpus extra for DXF comparison")

    files = sorted(path for path in CORPUS.iterdir() if path.is_file())
    assert len(files) == 19
    for path in files:
        mi_document = ezmi2d.read(path)
        dxf_path = DXF_CORPUS / f"{path.name}.DXF"
        assert dxf_path.is_file()
        dxf_document = ezdxf.readfile(dxf_path)
        modelspace = dxf_document.modelspace()

        mi_lines = Counter(_mi_line_key(entity) for entity in mi_document.query("LIN"))
        dxf_lines = Counter(_dxf_line_key(entity) for entity in modelspace.query("LINE"))
        assert mi_lines == dxf_lines, path.name

        mi_circles = Counter(_mi_circle_key(entity) for entity in mi_document.query("CIR"))
        dxf_circles = Counter(_dxf_circle_key(entity) for entity in modelspace.query("CIRCLE"))
        assert mi_circles == dxf_circles, path.name

        mi_arcs = Counter(_mi_arc_key(entity) for entity in mi_document.query("ARC"))
        dxf_arcs = Counter(_dxf_arc_key(entity) for entity in modelspace.query("ARC"))
        # Legacy FIL records become the additional DXF ARC entities.
        assert not (mi_arcs - dxf_arcs), path.name
        mi_fillets = Counter(_mi_arc_key(entity) for entity in mi_document.query("FIL"))
        assert mi_fillets == dxf_arcs - mi_arcs, path.name

        mi_splines = mi_document.query("BSPL")
        dxf_polylines = tuple(modelspace.query("POLYLINE"))
        assert len(mi_splines) == len(dxf_polylines)
        for spline, polyline in zip(mi_splines, dxf_polylines, strict=True):
            assert isinstance(spline, ezmi2d.BSpline)
            assert all(point is not None for point in spline.control_points)
            for sample in spline.samples:
                assert sample.point is not None
                assert spline.evaluate(sample.parameter).distance_to(
                    sample.point.location
                ) == pytest.approx(0.0, abs=1e-10)
            for vertex in polyline.vertices:
                assert _distance_to_spline(spline, vertex.dxf.location) < 1e-8

        mi_texts = Counter(_mi_text_key(entity) for entity in mi_document.query("TEXT"))
        dxf_texts = Counter(_dxf_text_key(entity) for entity in modelspace.query("TEXT"))
        assert mi_texts == dxf_texts, path.name

        assert mi_document.extents is not None
        assert _point_key(mi_document.extents.min) == _point_key(dxf_document.header["$EXTMIN"])
        assert _point_key(mi_document.extents.max) == _point_key(dxf_document.header["$EXTMAX"])

        raw_counts = Counter(record.record_type for record in mi_document.raw.records)
        dxf_counts = Counter(entity.dxftype() for entity in modelspace)
        assert dxf_counts["LINE"] == raw_counts["LIN"]
        assert dxf_counts["ARC"] == raw_counts["ARC"] + raw_counts["FIL"]
        assert dxf_counts["CIRCLE"] == raw_counts["CIR"]
        assert dxf_counts["TEXT"] == raw_counts["TEX"]
        assert dxf_counts["POLYLINE"] == raw_counts["BSPL"]


def test_product_generated_compressed_mi_matches_its_logical_payload() -> None:
    if not PTC_COMPRESSED_MI.is_file() or not PTC_LOGICAL_MI.is_file():
        pytest.skip("PTC compressed MI corpus has not been downloaded")

    compressed_bytes = PTC_COMPRESSED_MI.read_bytes()
    logical_bytes = PTC_LOGICAL_MI.read_bytes()
    assert hashlib.sha256(compressed_bytes).hexdigest() == (
        "60303e5f6dd38f434fd20b20798b3a9d3d9dfcb0e9883015119db6b3d1b49ecc"
    )
    assert hashlib.sha256(logical_bytes).hexdigest() == (
        "3bb45897b8cdbb9bc0e82048af65677274548002234c4a0190b4f0f14a1d1d65"
    )

    packed_scan = ezmi2d.scan(compressed_bytes)
    logical_scan = ezmi2d.scan(logical_bytes)
    assert packed_scan.format == ezmi2d.MiFormatInfo(
        kind="mi_text", compression="gzip", first_section=1, utf8_bom=False
    )
    assert packed_scan.container_size == 87_506
    assert packed_scan.source_size == 393_805
    assert packed_scan.container_bytes == compressed_bytes
    assert packed_scan.source_bytes == logical_scan.source_bytes == logical_bytes
    assert len(packed_scan.lines) == 55_160
    assert len(packed_scan.sections) == 144
    assert len(packed_scan.records) == 4_527
    assert packed_scan.diagnostics == logical_scan.diagnostics == ()

    packed = ezmi2d.read(compressed_bytes)
    logical = ezmi2d.read(logical_bytes)
    assert packed.version == logical.version == "3.40"
    assert packed.encoding == logical.encoding == "utf-8"
    assert len(packed.parts) == len(logical.parts) == 25
    assert len(packed.all_entities) == len(logical.all_entities) == 4_499
    assert len(packed.entities) == len(logical.entities) == 1_261
    assert len(packed.texts) == len(logical.texts) == 57
    assert len(packed.annotations) == len(logical.annotations) == 88
    assert len(packed.dimensions) == len(logical.dimensions) == 46
    assert len(packed.dimension_tolerances) == len(logical.dimension_tolerances) == 10
    assert len(packed.leaders) == len(logical.leaders) == 7
    assert len(packed.hatches) == len(logical.hatches) == 9
    assert len(packed.symbols) == len(logical.symbols) == 16
    assert len(packed.query("BSPL")) == len(logical.query("BSPL")) == 88
    assert len(packed.query("ARC")) == len(logical.query("ARC")) == 187
    assert all(
        isinstance(arc, ezmi2d.Arc)
        and arc.orientation == 0
        and arc.ccw is True
        and arc.display_values is None
        and arc.center is not None
        and arc.start is not None
        and arc.end is not None
        for arc in packed.query("ARC")
    )
    first_line = packed.query("LIN")[0]
    assert isinstance(first_line, ezmi2d.Line)
    assert first_line.display_values is None
    assert (first_line.color, first_line.linetype, first_line.lineweight) == (7, 0, 0.5)
    assert first_line.visibility is None
    assert first_line.visibility_value == 0
    assert len(first_line.properties) == 7
    assert all(
        isinstance(value, ezmi2d.AssociatedStringsProperty) for value in first_line.properties
    )

    rotated_texts = [text for text in packed.texts if text.rotation > 1e-12]
    assert len(rotated_texts) == 2
    assert all(text.rotation == pytest.approx(math.pi / 2.0) for text in rotated_texts)
    assert all(text.mirror is False for text in packed.texts)
    assert all(
        text.width_factor == pytest.approx(text.size_values[0] / text.size_values[1])
        for text in packed.texts
    )
    assert any(len(text.lines) > 1 for text in packed.texts)
    assert all(1 <= text.alignment <= 9 for text in packed.texts)
    assert all(
        isinstance(dimension.dimension_style, ezmi2d.DimensionDisplayAttributeProperty)
        and isinstance(dimension.text_style, ezmi2d.DimensionTextFormatProperty)
        and all(value is not None for value in dimension.reference_geometries)
        and all(value is not None for value in dimension.reference_points)
        and dimension.formatted_text is not None
        for dimension in packed.dimensions
    )
    assert sum(len(dimension.tolerance_ids) for dimension in packed.dimensions) == 10
    assert all(
        isinstance(tolerance.text_style, ezmi2d.DimensionTextFormatProperty)
        and tolerance.upper_text is not None
        and tolerance.lower_text is not None
        for tolerance in packed.dimension_tolerances
    )
    assert all(
        len(leader.vertices) == 2
        and len(leader.points) == 2
        and all(point.elevation == 0.0 for point in leader.points)
        for leader in packed.leaders
    )
    assert len(packed.contours) == 11
    assert all(contour.closed and contour.orientation == 0 for contour in packed.contours)
    assert (
        sum(component is None for contour in packed.contours for component in contour.components)
        == 1
    )
    assert len(packed.hatch_associations) == 9
    assert sorted(len(hatch.boundary_loops) for hatch in packed.hatches) == [1] * 8 + [3]
    assert all(hatch.pattern is packed.get(30) for hatch in packed.hatches)
    assert isinstance(packed.get(30), ezmi2d.HatchPatternProperty)
    assert packed.get(30).lines == (
        ezmi2d.HatchPatternLine(
            offset=0.0,
            distance=1.0,
            angle=0.0,
            color=667546301,
            linetype=0,
        ),
    )
    assert all(
        association.hatch is not None
        and association.outer_loop is not None
        and all(loop is not None for loop in association.inner_loops)
        for association in packed.hatch_associations
    )
    assert all(
        len(symbol.components) == 3 and all(value is not None for value in symbol.components)
        for symbol in packed.symbols
    )
    assert all(
        all(point is not None for point in spline.control_points)
        for spline in packed.query("BSPL")
        if isinstance(spline, ezmi2d.BSpline)
    )
    assert packed.top_part is not None
    assert packed.top_part.name == "MANDRIL`~18"
    assert [part.name for part in packed.root_parts] == ["MANDRIL`~18"]
    assert [part.name for part in packed.sheets] == ["1"]
    assert len(packed.assemblies) == 25
    assert sum(len(assembly.instances) for assembly in packed.assemblies) == 24
    assert packed.assemblies[-1].part_name == "MANDRIL`~18"
    assert packed.assemblies[-1].property_ids == (57, 58, 59, 33, 28)
    assert packed.global_info == logical.global_info
    assert packed.parts == logical.parts
    assert packed.all_entities == logical.all_entities
    assert packed.diagnostics == logical.diagnostics


def _geometry_is_resolved(entity: ezmi2d.Graphic) -> bool:
    if isinstance(entity, ezmi2d.Line):
        return entity.start is not None and entity.end is not None
    if isinstance(entity, ezmi2d.Arc):
        return entity.center is not None and entity.start is not None and entity.end is not None
    if isinstance(entity, ezmi2d.Circle):
        return (
            entity.center is not None
            and entity.circumference is not None
            and entity.radius is not None
        )
    if isinstance(entity, ezmi2d.BSpline):
        return all(point is not None for point in entity.control_points)
    return isinstance(entity, ezmi2d.Text)


def _distance_to_spline(spline: ezmi2d.BSpline, point: Any) -> float:
    """Find the curve distance using a grid bracket followed by golden-section search."""

    start, end = spline.parameter_domain
    divisions = 256
    step = (end - start) / divisions

    def distance_squared(parameter: float) -> float:
        value = spline.evaluate(parameter)
        return (value.x - float(point.x)) ** 2 + (value.y - float(point.y)) ** 2

    distances = [distance_squared(start + index * step) for index in range(divisions + 1)]
    best_index = min(range(divisions + 1), key=distances.__getitem__)
    low = max(start, start + (best_index - 1) * step)
    high = min(end, start + (best_index + 1) * step)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left = high - ratio * (high - low)
    right = low + ratio * (high - low)
    left_distance = distance_squared(left)
    right_distance = distance_squared(right)
    for _ in range(64):
        if left_distance < right_distance:
            high, right, right_distance = right, left, left_distance
            left = high - ratio * (high - low)
            left_distance = distance_squared(left)
        else:
            low, left, left_distance = left, right, right_distance
            right = low + ratio * (high - low)
            right_distance = distance_squared(right)
    return math.sqrt(min(distances[best_index], left_distance, right_distance))


def _point_key(value: Any) -> tuple[float, float]:
    try:
        x, y = value.x, value.y
    except AttributeError:
        x, y = value[0], value[1]
    return round(float(x), 7), round(float(y), 7)


def _mi_line_key(entity: ezmi2d.Graphic) -> tuple[tuple[float, float], tuple[float, float]]:
    assert isinstance(entity, ezmi2d.Line)
    assert entity.start is not None and entity.end is not None
    return tuple(sorted((_point_key(entity.start), _point_key(entity.end))))


def _dxf_line_key(entity: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    return tuple(sorted((_point_key(entity.dxf.start), _point_key(entity.dxf.end))))


def _mi_arc_key(
    entity: ezmi2d.Graphic,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    assert isinstance(entity, ezmi2d.Arc)
    assert entity.center is not None and entity.start is not None and entity.end is not None
    return _point_key(entity.center), _point_key(entity.start), _point_key(entity.end)


def _dxf_arc_key(
    entity: Any,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    return (
        _point_key(entity.dxf.center),
        _point_key(entity.start_point),
        _point_key(entity.end_point),
    )


def _mi_circle_key(entity: ezmi2d.Graphic) -> tuple[tuple[float, float], float]:
    assert isinstance(entity, ezmi2d.Circle)
    assert entity.center is not None and entity.radius is not None
    return _point_key(entity.center), round(entity.radius, 7)


def _dxf_circle_key(entity: Any) -> tuple[tuple[float, float], float]:
    return _point_key(entity.dxf.center), round(float(entity.dxf.radius), 7)


def _mi_text_key(
    entity: ezmi2d.Graphic,
) -> tuple[str, tuple[float, float], float]:
    assert isinstance(entity, ezmi2d.Text)
    assert entity.text is not None
    insertion = (entity.origin.x, entity.origin.y - entity.height / 2.0)
    return entity.text, _point_key(insertion), round(entity.height, 7)


def _dxf_text_key(entity: Any) -> tuple[str, tuple[float, float], float]:
    # The paired R12 files omit $DWGCODEPAGE. ezdxf therefore exposes their CP932
    # bytes through its cp1252/surrogateescape fallback; reconstruct those bytes first.
    raw_text = str(entity.dxf.text).encode("cp1252", errors="surrogateescape")
    text = raw_text.decode("cp932")
    return text, _point_key(entity.dxf.insert), round(float(entity.dxf.height), 7)
