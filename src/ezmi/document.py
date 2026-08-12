"""High-level MI document, entity, annotation, and part API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ._core import read_legacy_document as _read_legacy_document
from .diagnostics import Diagnostic
from .entities import (
    AddressableEntity,
    Annotation,
    Arc,
    Assembly,
    AssemblyInstance,
    Bounds2,
    BSpline,
    BSplineSample,
    Circle,
    Dimension,
    DimensionTolerance,
    Fillet,
    Graphic,
    Hatch,
    Leader,
    Line,
    MiEntity,
    Point,
    Property,
    StructuredEntity,
    Symbol,
    Text,
    TextValue,
    UnsupportedEntity,
    Vec2,
    query_annotation_entities,
    query_entities,
)
from .raw import (
    MiSource,
    PathSource,
    RawScan,
    ScanLimits,
    _diagnostic_from_core,
    _mapping,
    _read_all,
    _scan_from_core,
)


@dataclass(frozen=True, slots=True)
class EncodingInfo:
    name: str | None
    source: str
    declared_name: str | None


@dataclass(frozen=True, slots=True)
class GlobalInfo:
    section_index: int
    drawing_name_value: TextValue | None
    creation_date_value: TextValue | None
    creation_time_value: TextValue | None
    producer_value: TextValue | None
    version: str | None
    dimension: str | None
    extents: Bounds2 | None
    paper_size: str | None
    drawing_scale: float | None
    unit: str | None
    angle_unit: str | None
    transform_values: tuple[float, ...] | None

    @property
    def drawing_name(self) -> str | None:
        return None if self.drawing_name_value is None else self.drawing_name_value.text

    @property
    def drawing_name_bytes(self) -> bytes | None:
        if self.drawing_name_value is None:
            return None
        return self.drawing_name_value.raw_bytes

    @property
    def creation_date(self) -> str | None:
        return None if self.creation_date_value is None else self.creation_date_value.text

    @property
    def creation_time(self) -> str | None:
        return None if self.creation_time_value is None else self.creation_time_value.text

    @property
    def producer(self) -> str | None:
        return None if self.producer_value is None else self.producer_value.text


@dataclass(frozen=True, slots=True)
class Part:
    index: int
    name_value: TextValue
    definition_section_index: int
    points: tuple[Point, ...]
    entities: tuple[Graphic, ...]
    texts: tuple[Text, ...]
    annotations: tuple[Annotation, ...]
    unsupported_entities: tuple[UnsupportedEntity, ...]
    source_entities: tuple[AddressableEntity, ...]
    assembly_id: int | None
    assembly: Assembly | None
    child_part_indices: tuple[int, ...]
    parent_part_indices: tuple[int, ...]

    @property
    def name(self) -> str | None:
        return self.name_value.text

    @property
    def name_bytes(self) -> bytes:
        return self.name_value.raw_bytes

    def query(self, query: str = "*") -> tuple[Graphic, ...]:
        return query_entities(self.entities, query)

    def query_annotations(self, query: str = "*") -> tuple[Annotation, ...]:
        return query_annotation_entities(self.annotations, query)

    @property
    def instances(self) -> tuple[AssemblyInstance, ...]:
        return () if self.assembly is None else self.assembly.instances


@dataclass(frozen=True, slots=True)
class Document:
    raw: RawScan
    encoding_info: EncodingInfo
    global_info: GlobalInfo | None
    toc_last_entity: int | None
    parts: tuple[Part, ...]
    top_part_index: int | None
    root_part_indices: tuple[int, ...]
    sheet_part_indices: tuple[int, ...]
    all_entities: tuple[AddressableEntity, ...]
    entitydb: Mapping[int, AddressableEntity]
    points: tuple[Point, ...]
    entities: tuple[Graphic, ...]
    texts: tuple[Text, ...]
    annotations: tuple[Annotation, ...]
    dimensions: tuple[Dimension, ...]
    dimension_tolerances: tuple[DimensionTolerance, ...]
    leaders: tuple[Leader, ...]
    hatches: tuple[Hatch, ...]
    symbols: tuple[Symbol, ...]
    properties: tuple[Property, ...]
    assemblies: tuple[Assembly, ...]
    unsupported_entities: tuple[UnsupportedEntity, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def encoding(self) -> str | None:
        return self.encoding_info.name

    @property
    def encoding_source(self) -> str:
        return self.encoding_info.source

    @property
    def declared_encoding(self) -> str | None:
        return self.encoding_info.declared_name

    @property
    def header(self) -> GlobalInfo | None:
        return self.global_info

    @property
    def version(self) -> str | None:
        return None if self.global_info is None else self.global_info.version

    @property
    def units(self) -> str | None:
        return None if self.global_info is None else self.global_info.unit

    @property
    def extents(self) -> Bounds2 | None:
        return None if self.global_info is None else self.global_info.extents

    @property
    def top_part(self) -> Part | None:
        if self.top_part_index is None:
            return None
        return self.parts[self.top_part_index]

    @property
    def root_parts(self) -> tuple[Part, ...]:
        return tuple(self.parts[index] for index in self.root_part_indices)

    @property
    def sheets(self) -> tuple[Part, ...]:
        """Return parts linked through a verified ``DOCU_SHEET`` association."""

        return tuple(self.parts[index] for index in self.sheet_part_indices)

    def modelspace(self) -> Part:
        """Return the TOP part without recursively flattening child parts."""

        part = self.top_part
        if part is None:
            raise LookupError("MI document has no part definition")
        return part

    def query(self, query: str = "*") -> tuple[Graphic, ...]:
        """Query graphic entities across all directly decoded parts."""

        return query_entities(self.entities, query)

    def query_annotations(self, query: str = "*") -> tuple[Annotation, ...]:
        """Query typed annotation records across all parts and global sections."""

        return query_annotation_entities(self.annotations, query)

    def get(self, entity_id: int) -> AddressableEntity | None:
        return self.entitydb.get(entity_id)

    def part_for(self, entity: MiEntity) -> Part | None:
        if isinstance(entity, Assembly) and entity.definition_part_index is not None:
            return self.parts[entity.definition_part_index]
        if entity.part_index is None:
            return None
        return self.parts[entity.part_index]

    def child_parts(self, part: Part) -> tuple[Part, ...]:
        return tuple(self.parts[index] for index in part.child_part_indices)

    def parent_parts(self, part: Part) -> tuple[Part, ...]:
        return tuple(self.parts[index] for index in part.parent_part_indices)


Drawing = Document


def read(
    source: MiSource,
    *,
    limits: ScanLimits | None = None,
    encoding: str | None = None,
) -> Document:
    """Read verified MI geometry, annotations, and part structure."""

    selected_limits = limits or ScanLimits()
    core_limits = selected_limits.as_core_list()
    data = _read_all(source, max_file_size=selected_limits.max_file_size)
    row = _mapping(_read_legacy_document(data, core_limits, encoding))
    return _document_from_core(data, row)


def readfile(
    path: PathSource,
    *,
    limits: ScanLimits | None = None,
    encoding: str | None = None,
) -> Document:
    return read(path, limits=limits, encoding=encoding)


def _document_from_core(data: bytes, row: Mapping[str, Any]) -> Document:
    raw = _scan_from_core(data, _mapping(row["raw"]))
    entity_rows = tuple(_mapping(value) for value in row["entities"])
    raw_records = raw.records

    built: list[AddressableEntity | None] = [None] * len(entity_rows)
    for index, entity_row in enumerate(entity_rows):
        kind = entity_row["kind"]
        if kind == "point":
            built[index] = _point_from_core(entity_row, raw_records)
        elif kind == "property":
            built[index] = _property_from_core(entity_row, raw_records)
        elif kind == "assembly":
            built[index] = _assembly_from_core(entity_row, raw_records)
        elif kind == "dimension":
            built[index] = _structured_from_core(Dimension, entity_row, raw_records)
        elif kind == "dimension_tolerance":
            built[index] = _structured_from_core(DimensionTolerance, entity_row, raw_records)
        elif kind == "leader":
            built[index] = _structured_from_core(Leader, entity_row, raw_records)
        elif kind == "hatch":
            built[index] = _structured_from_core(Hatch, entity_row, raw_records)
        elif kind == "symbol":
            built[index] = _structured_from_core(Symbol, entity_row, raw_records)
        elif kind == "unsupported":
            built[index] = _unsupported_from_core(entity_row, raw_records)
        elif kind not in {"line", "arc", "fillet", "bspline", "circle", "text"}:
            raise RuntimeError(f"native core returned unknown semantic entity kind: {kind!r}")

    pointdb: dict[int, Point] = {}
    propertydb: dict[int, Property] = {}
    seen_ids: set[int] = set()
    for entity_row, entity in zip(entity_rows, built, strict=True):
        entity_id = int(entity_row["id"])
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        if isinstance(entity, Point):
            pointdb.setdefault(entity.id, entity)
        elif isinstance(entity, Property):
            propertydb.setdefault(entity.id, entity)

    for index, entity_row in enumerate(entity_rows):
        kind = entity_row["kind"]
        if kind == "line":
            built[index] = _line_from_core(entity_row, raw_records, pointdb, propertydb)
        elif kind == "arc":
            built[index] = _arc_from_core(entity_row, raw_records, pointdb, propertydb)
        elif kind == "fillet":
            built[index] = _fillet_from_core(entity_row, raw_records, pointdb, propertydb)
        elif kind == "bspline":
            built[index] = _bspline_from_core(entity_row, raw_records, pointdb, propertydb)
        elif kind == "circle":
            built[index] = _circle_from_core(entity_row, raw_records, pointdb, propertydb)
        elif kind == "text":
            built[index] = _text_entity_from_core(entity_row, raw_records, propertydb)

    missing = [index for index, entity in enumerate(built) if entity is None]
    if missing:
        raise RuntimeError(
            f"native core left semantic entities unconstructed at indexes: {missing}"
        )
    all_entities = tuple(cast(AddressableEntity, entity) for entity in built)
    entitydb_mutable: dict[int, AddressableEntity] = {}
    for entity in all_entities:
        entitydb_mutable.setdefault(entity.id, entity)

    assemblydb = {entity.id: entity for entity in all_entities if isinstance(entity, Assembly)}
    parts = tuple(
        _part_from_core(_mapping(part_row), all_entities, assemblydb) for part_row in row["parts"]
    )
    global_row = row["global"]
    diagnostics = tuple(_diagnostic_from_core(_mapping(value)) for value in row["diagnostics"])
    return Document(
        raw=raw,
        encoding_info=_encoding_from_core(_mapping(row["encoding"])),
        global_info=(None if global_row is None else _global_from_core(_mapping(global_row))),
        toc_last_entity=(None if row["toc_last_entity"] is None else int(row["toc_last_entity"])),
        parts=parts,
        top_part_index=(None if row["top_part_index"] is None else int(row["top_part_index"])),
        root_part_indices=tuple(int(value) for value in row["root_part_indices"]),
        sheet_part_indices=tuple(int(value) for value in row["sheet_part_indices"]),
        all_entities=all_entities,
        entitydb=MappingProxyType(entitydb_mutable),
        points=tuple(entity for entity in all_entities if isinstance(entity, Point)),
        entities=tuple(
            cast(Graphic, entity)
            for entity in all_entities
            if isinstance(entity, (Line, Arc, Fillet, BSpline, Circle, Text))
        ),
        texts=tuple(entity for entity in all_entities if isinstance(entity, Text)),
        annotations=tuple(
            cast(Annotation, entity)
            for entity in all_entities
            if isinstance(entity, (Dimension, DimensionTolerance, Leader, Hatch, Symbol))
        ),
        dimensions=tuple(entity for entity in all_entities if isinstance(entity, Dimension)),
        dimension_tolerances=tuple(
            entity for entity in all_entities if isinstance(entity, DimensionTolerance)
        ),
        leaders=tuple(entity for entity in all_entities if isinstance(entity, Leader)),
        hatches=tuple(entity for entity in all_entities if isinstance(entity, Hatch)),
        symbols=tuple(entity for entity in all_entities if isinstance(entity, Symbol)),
        properties=tuple(entity for entity in all_entities if isinstance(entity, Property)),
        assemblies=tuple(entity for entity in all_entities if isinstance(entity, Assembly)),
        unsupported_entities=tuple(
            entity for entity in all_entities if isinstance(entity, UnsupportedEntity)
        ),
        diagnostics=diagnostics,
    )


def _base_fields(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "mi_type": str(row["mi_type"]),
        "raw_record": raw_records[int(row["raw_record_index"])],
        "part_index": None if row["part_index"] is None else int(row["part_index"]),
    }


def _graphic_fields(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    propertydb: Mapping[int, Property],
) -> dict[str, Any]:
    raw_display_values = row["display_values"]
    values = (
        None if raw_display_values is None else tuple(int(value) for value in raw_display_values)
    )
    if values is not None and len(values) != 4:
        raise ValueError(f"native display_values length is {len(values)}, expected 4")
    property_id = None if row["property_id"] is None else int(row["property_id"])
    return {
        **_base_fields(row, raw_records),
        "display_values": cast(tuple[int, int, int, int] | None, values),
        "property_id": property_id,
        "property": None if property_id is None else propertydb.get(property_id),
    }


def _point_from_core(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> Point:
    return Point(
        **_base_fields(row, raw_records), location=_vec_from_core(_mapping(row["location"]))
    )


def _property_from_core(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> Property:
    return Property(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _assembly_from_core(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> Assembly:
    value = row["part_name"]
    return Assembly(
        **_base_fields(row, raw_records),
        property_ids=tuple(int(item) for item in row["property_ids"]),
        part_name_value=None if value is None else _text_from_core(_mapping(value)),
        instances=tuple(_assembly_instance_from_core(_mapping(item)) for item in row["instances"]),
        definition_part_index=(
            None if row["definition_part_index"] is None else int(row["definition_part_index"])
        ),
        values=tuple(bytes(item) for item in row["values"]),
    )


def _assembly_instance_from_core(row: Mapping[str, Any]) -> AssemblyInstance:
    definition_values = tuple(bytes(value) for value in row["definition_values"])
    if len(definition_values) != 3:
        raise ValueError(
            f"native assembly definition length is {len(definition_values)}, expected 3"
        )
    transform_values = tuple(float(value) for value in row["transform_values"])
    if len(transform_values) != 9:
        raise ValueError(f"native assembly transform length is {len(transform_values)}, expected 9")
    return AssemblyInstance(
        relation_value=(None if row["relation_value"] is None else bytes(row["relation_value"])),
        definition_values=cast(tuple[bytes, bytes, bytes], definition_values),
        member_ids=tuple(int(value) for value in row["member_ids"]),
        assembly_id=int(row["assembly_id"]),
        transform_values=transform_values,
        target_part_index=(
            None if row["target_part_index"] is None else int(row["target_part_index"])
        ),
        is_sheet=bool(row["is_sheet"]),
    )


def _structured_from_core(
    entity_type: type[StructuredEntity],
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
) -> StructuredEntity:
    return entity_type(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _unsupported_from_core(
    row: Mapping[str, Any], raw_records: tuple[Any, ...]
) -> UnsupportedEntity:
    return UnsupportedEntity(**_base_fields(row, raw_records))


def _line_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    propertydb: Mapping[int, Property],
) -> Line:
    start_id = int(row["start_id"])
    end_id = int(row["end_id"])
    return Line(
        **_graphic_fields(row, raw_records, propertydb),
        start_id=start_id,
        end_id=end_id,
        start_point=pointdb.get(start_id),
        end_point=pointdb.get(end_id),
    )


def _arc_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    propertydb: Mapping[int, Property],
) -> Arc:
    center_id = int(row["center_id"])
    start_id = int(row["start_id"])
    end_id = int(row["end_id"])
    return Arc(
        **_graphic_fields(row, raw_records, propertydb),
        center_id=center_id,
        start_id=start_id,
        end_id=end_id,
        orientation=int(row["orientation"]),
        center_point=pointdb.get(center_id),
        start_point=pointdb.get(start_id),
        end_point=pointdb.get(end_id),
        radius=None if row["radius"] is None else float(row["radius"]),
        start_angle=None if row["start_angle"] is None else float(row["start_angle"]),
        end_angle=None if row["end_angle"] is None else float(row["end_angle"]),
    )


def _fillet_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    propertydb: Mapping[int, Property],
) -> Fillet:
    center_id = int(row["center_id"])
    start_id = int(row["start_id"])
    end_id = int(row["end_id"])
    return Fillet(
        **_graphic_fields(row, raw_records, propertydb),
        center_id=center_id,
        start_id=start_id,
        end_id=end_id,
        orientation=int(row["orientation"]),
        center_point=pointdb.get(center_id),
        start_point=pointdb.get(start_id),
        end_point=pointdb.get(end_id),
        radius=None if row["radius"] is None else float(row["radius"]),
        start_angle=None if row["start_angle"] is None else float(row["start_angle"]),
        end_angle=None if row["end_angle"] is None else float(row["end_angle"]),
    )


def _bspline_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    propertydb: Mapping[int, Property],
) -> BSpline:
    definition_values = tuple(bytes(value) for value in row["definition_values"])
    if len(definition_values) != 2:
        raise ValueError(f"native spline definition length is {len(definition_values)}, expected 2")
    domain = tuple(float(value) for value in row["parameter_domain"])
    if len(domain) != 2:
        raise ValueError(f"native spline domain length is {len(domain)}, expected 2")
    control_point_ids = tuple(int(value) for value in row["control_point_ids"])
    start_id = int(row["start_id"])
    end_id = int(row["end_id"])
    samples: list[BSplineSample] = []
    for item in row["samples"]:
        sample = _mapping(item)
        sample_values = tuple(float(value) for value in sample["definition_values"])
        if len(sample_values) != 5:
            raise ValueError(
                f"native spline sample definition length is {len(sample_values)}, expected 5"
            )
        point_id = int(sample["point_id"])
        samples.append(
            BSplineSample(
                point_id=point_id,
                parameter=float(sample["parameter"]),
                definition_values=cast(tuple[float, float, float, float, float], sample_values),
                point=pointdb.get(point_id),
            )
        )
    return BSpline(
        **_graphic_fields(row, raw_records, propertydb),
        prefix_values=tuple(bytes(value) for value in row["prefix_values"]),
        order=int(row["order"]),
        degree=int(row["degree"]),
        definition_values=cast(tuple[bytes, bytes], definition_values),
        parameter_max=float(row["parameter_max"]),
        parameter_domain=cast(tuple[float, float], domain),
        start_id=start_id,
        end_id=end_id,
        start_point=pointdb.get(start_id),
        end_point=pointdb.get(end_id),
        control_point_ids=control_point_ids,
        control_points=tuple(pointdb.get(point_id) for point_id in control_point_ids),
        knots=tuple(float(value) for value in row["knots"]),
        samples=tuple(samples),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _circle_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    propertydb: Mapping[int, Property],
) -> Circle:
    center_id = int(row["center_id"])
    circumference_id = int(row["circumference_id"])
    return Circle(
        **_graphic_fields(row, raw_records, propertydb),
        center_id=center_id,
        circumference_id=circumference_id,
        center_point=pointdb.get(center_id),
        circumference_point=pointdb.get(circumference_id),
        radius=None if row["radius"] is None else float(row["radius"]),
    )


def _text_entity_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    propertydb: Mapping[int, Property],
) -> Text:
    transform_values = tuple(float(value) for value in row["transform_values"])
    if len(transform_values) != 9:
        raise ValueError(f"native text transform length is {len(transform_values)}, expected 9")
    size_values = tuple(float(value) for value in row["size_values"])
    if len(size_values) != 2:
        raise ValueError(f"native text size length is {len(size_values)}, expected 2")
    return Text(
        **_graphic_fields(row, raw_records, propertydb),
        transform_values=transform_values,
        origin=_vec_from_core(_mapping(row["origin"])),
        font_name_value=_text_from_core(_mapping(row["font_name"])),
        size_values=cast(tuple[float, float], size_values),
        height=float(row["height"]),
        content_value=_text_from_core(_mapping(row["content"])),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _part_from_core(
    row: Mapping[str, Any],
    entities: tuple[AddressableEntity, ...],
    assemblydb: Mapping[int, Assembly],
) -> Part:
    index = int(row["index"])
    source_entities = tuple(entity for entity in entities if entity.part_index == index)
    assembly_id = None if row["assembly_id"] is None else int(row["assembly_id"])
    return Part(
        index=index,
        name_value=_text_from_core(_mapping(row["name"])),
        definition_section_index=int(row["definition_section_index"]),
        points=tuple(entity for entity in source_entities if isinstance(entity, Point)),
        entities=tuple(
            cast(Graphic, entity)
            for entity in source_entities
            if isinstance(entity, (Line, Arc, Fillet, BSpline, Circle, Text))
        ),
        texts=tuple(entity for entity in source_entities if isinstance(entity, Text)),
        annotations=tuple(
            cast(Annotation, entity)
            for entity in source_entities
            if isinstance(entity, (Dimension, DimensionTolerance, Leader, Hatch, Symbol))
        ),
        unsupported_entities=tuple(
            entity for entity in source_entities if isinstance(entity, UnsupportedEntity)
        ),
        source_entities=source_entities,
        assembly_id=assembly_id,
        assembly=None if assembly_id is None else assemblydb.get(assembly_id),
        child_part_indices=tuple(int(value) for value in row["child_part_indices"]),
        parent_part_indices=tuple(int(value) for value in row["parent_part_indices"]),
    )


def _global_from_core(row: Mapping[str, Any]) -> GlobalInfo:
    extents_row = row["extents"]
    transform = row["transform_values"]
    return GlobalInfo(
        section_index=int(row["section_index"]),
        drawing_name_value=_optional_text(row["drawing_name"]),
        creation_date_value=_optional_text(row["creation_date"]),
        creation_time_value=_optional_text(row["creation_time"]),
        producer_value=_optional_text(row["producer"]),
        version=None if row["version"] is None else str(row["version"]),
        dimension=None if row["dimension"] is None else str(row["dimension"]),
        extents=None if extents_row is None else _bounds_from_core(_mapping(extents_row)),
        paper_size=None if row["paper_size"] is None else str(row["paper_size"]),
        drawing_scale=None if row["drawing_scale"] is None else float(row["drawing_scale"]),
        unit=None if row["unit"] is None else str(row["unit"]),
        angle_unit=None if row["angle_unit"] is None else str(row["angle_unit"]),
        transform_values=(
            None if transform is None else tuple(float(value) for value in transform)
        ),
    )


def _optional_text(value: object) -> TextValue | None:
    return None if value is None else _text_from_core(_mapping(value))


def _text_from_core(row: Mapping[str, Any]) -> TextValue:
    return TextValue(
        raw_bytes=bytes(row["bytes"]),
        text=None if row["text"] is None else str(row["text"]),
        encoding=None if row["encoding"] is None else str(row["encoding"]),
    )


def _encoding_from_core(row: Mapping[str, Any]) -> EncodingInfo:
    return EncodingInfo(
        name=None if row["name"] is None else str(row["name"]),
        source=str(row["source"]),
        declared_name=(None if row["declared_name"] is None else str(row["declared_name"])),
    )


def _vec_from_core(row: Mapping[str, Any]) -> Vec2:
    return Vec2(x=float(row["x"]), y=float(row["y"]))


def _bounds_from_core(row: Mapping[str, Any]) -> Bounds2:
    return Bounds2(
        min=_vec_from_core(_mapping(row["min"])),
        max=_vec_from_core(_mapping(row["max"])),
    )
