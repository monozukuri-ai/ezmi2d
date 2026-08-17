"""High-level MI document, entity, annotation, and part API."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ._core import read_legacy_document as _read_legacy_document
from .diagnostics import Diagnostic
from .entities import (
    AddressableEntity,
    Affine2D,
    Annotation,
    Arc,
    Assembly,
    AssemblyInstance,
    AssociatedStringsProperty,
    Bounds2,
    BSpline,
    BSplineSample,
    Circle,
    Contour,
    Dimension,
    DimensionArrowProperty,
    DimensionDisplayAttributeProperty,
    DimensionLineAttributeProperty,
    DimensionTextAttributeProperty,
    DimensionTextFormatProperty,
    DimensionTolerance,
    Fillet,
    Graphic,
    Hatch,
    HatchAssociation,
    HatchPatternLine,
    HatchPatternProperty,
    Leader,
    LeaderPoint,
    Line,
    MiEntity,
    PartStatusProperty,
    Point,
    Property,
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
    contours: tuple[Contour, ...]
    hatch_associations: tuple[HatchAssociation, ...]
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
class InstancePathStep:
    """Stable identity for one child entry in an ASSE record."""

    assembly_id: int
    instance_index: int


@dataclass(frozen=True, slots=True)
class PartOccurrence:
    """One placed occurrence of a part definition in an assembly tree."""

    part: Part
    instance: AssemblyInstance | None
    instance_index: int | None
    path: tuple[InstancePathStep, ...]
    local_transform: Affine2D
    world_transform: Affine2D
    parent_part_index: int | None
    is_sheet: bool

    @property
    def is_root(self) -> bool:
        return self.instance is None


@dataclass(frozen=True, slots=True)
class PlacedGraphic:
    """A graphic definition paired with its assembly occurrence transform."""

    entity: Graphic
    occurrence: PartOccurrence

    @property
    def world_transform(self) -> Affine2D:
        return self.occurrence.world_transform


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
    contours: tuple[Contour, ...]
    hatch_associations: tuple[HatchAssociation, ...]
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

    def iter_part_occurrences(
        self,
        root: Part | None = None,
        *,
        include_root: bool = True,
        strict: bool = True,
    ) -> Iterator[PartOccurrence]:
        """Traverse placed part occurrences in source instance order.

        Shared definitions are yielded once per instance path. ``world_transform``
        maps geometry from the yielded part's local coordinates into ``root``
        coordinates. Unbound, non-affine, and cyclic instances raise by default;
        pass ``strict=False`` to omit those branches.
        """

        selected_root = self.top_part if root is None else root
        if selected_root is None:
            return
        if not (0 <= selected_root.index < len(self.parts)):
            raise ValueError("root part index is outside this document")
        if self.parts[selected_root.index] is not selected_root:
            raise ValueError("root part does not belong to this document")

        identity = Affine2D.identity()
        root_occurrence = PartOccurrence(
            part=selected_root,
            instance=None,
            instance_index=None,
            path=(),
            local_transform=identity,
            world_transform=identity,
            parent_part_index=None,
            is_sheet=False,
        )
        stack: list[tuple[PartOccurrence, tuple[int, ...]]] = [
            (root_occurrence, (selected_root.index,))
        ]
        while stack:
            occurrence, ancestry = stack.pop()
            if include_root or not occurrence.is_root:
                yield occurrence

            assembly = occurrence.part.assembly
            if assembly is None:
                continue
            children: list[tuple[PartOccurrence, tuple[int, ...]]] = []
            for instance_index, instance in enumerate(assembly.instances):
                target_index = instance.target_part_index
                if target_index is None or not (0 <= target_index < len(self.parts)):
                    if strict:
                        raise LookupError(
                            f"ASSE {assembly.id} instance {instance_index} has no bound part"
                        )
                    continue
                if target_index in ancestry:
                    if strict:
                        path = (*occurrence.path, InstancePathStep(assembly.id, instance_index))
                        raise ValueError(f"assembly cycle at instance path {path!r}")
                    continue
                try:
                    local_transform = instance.to_affine2d()
                except (TypeError, ValueError):
                    if strict:
                        raise
                    continue
                child = self.parts[target_index]
                path = (*occurrence.path, InstancePathStep(assembly.id, instance_index))
                child_occurrence = PartOccurrence(
                    part=child,
                    instance=instance,
                    instance_index=instance_index,
                    path=path,
                    local_transform=local_transform,
                    world_transform=occurrence.world_transform.compose(local_transform),
                    parent_part_index=occurrence.part.index,
                    is_sheet=instance.is_sheet,
                )
                children.append((child_occurrence, (*ancestry, target_index)))
            stack.extend(reversed(children))

    def iter_instances(
        self,
        root: Part | None = None,
        *,
        strict: bool = True,
    ) -> Iterator[PartOccurrence]:
        """Traverse non-root part occurrences, including shared and sheet instances."""

        yield from self.iter_part_occurrences(root, include_root=False, strict=strict)

    @property
    def sheet_instances(self) -> tuple[PartOccurrence, ...]:
        return tuple(occurrence for occurrence in self.iter_instances() if occurrence.is_sheet)

    def iter_placed_graphics(
        self,
        root: Part | None = None,
        *,
        strict: bool = True,
    ) -> Iterator[PlacedGraphic]:
        """Yield graphics once per placed part occurrence."""

        for occurrence in self.iter_part_occurrences(root, strict=strict):
            for entity in occurrence.part.entities:
                yield PlacedGraphic(entity=entity, occurrence=occurrence)


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
        elif kind == "unsupported":
            built[index] = _unsupported_from_core(entity_row, raw_records)
        elif kind not in {
            "line",
            "arc",
            "fillet",
            "bspline",
            "circle",
            "text",
            "dimension",
            "dimension_tolerance",
            "leader",
            "contour",
            "hatch",
            "hatch_association",
            "symbol",
        }:
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
        elif kind == "dimension_tolerance":
            built[index] = _dimension_tolerance_from_core(entity_row, raw_records, propertydb)
        elif kind == "leader":
            built[index] = _leader_from_core(entity_row, raw_records, propertydb)

    graphicdb: dict[int, Graphic] = {}
    tolerancedb: dict[int, DimensionTolerance] = {}
    for entity in built:
        if isinstance(entity, (Line, Arc, Fillet, BSpline, Circle, Text)):
            graphicdb.setdefault(entity.id, entity)
        elif isinstance(entity, DimensionTolerance):
            tolerancedb.setdefault(entity.id, entity)

    for index, entity_row in enumerate(entity_rows):
        kind = entity_row["kind"]
        if kind == "dimension":
            built[index] = _dimension_from_core(
                entity_row,
                raw_records,
                pointdb,
                graphicdb,
                propertydb,
                tolerancedb,
            )
        elif kind == "contour":
            built[index] = _contour_from_core(entity_row, raw_records, graphicdb, propertydb)
        elif kind == "symbol":
            built[index] = _symbol_from_core(entity_row, raw_records, graphicdb)

    contourdb = {entity.id: entity for entity in built if isinstance(entity, Contour)}
    for index, entity_row in enumerate(entity_rows):
        if entity_row["kind"] == "hatch":
            built[index] = _hatch_from_core(entity_row, raw_records, contourdb, propertydb)

    hatchdb = {entity.id: entity for entity in built if isinstance(entity, Hatch)}
    for index, entity_row in enumerate(entity_rows):
        if entity_row["kind"] == "hatch_association":
            built[index] = _hatch_association_from_core(
                entity_row,
                raw_records,
                hatchdb,
                contourdb,
                propertydb,
            )

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
        contours=tuple(entity for entity in all_entities if isinstance(entity, Contour)),
        hatch_associations=tuple(
            entity for entity in all_entities if isinstance(entity, HatchAssociation)
        ),
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
    property_ids = tuple(int(value) for value in row["property_ids"])
    property_id = None if row["property_id"] is None else int(row["property_id"])
    properties = tuple(
        property_value
        for property_value in (propertydb.get(value) for value in property_ids)
        if property_value is not None
    )
    return {
        **_base_fields(row, raw_records),
        "display_values": cast(tuple[int, int, int, int] | None, values),
        "color": int(row["color"]),
        "linetype": int(row["linetype"]),
        "lineweight": float(row["lineweight"]),
        "visibility": None if row["visibility"] is None else bool(row["visibility"]),
        "visibility_value": (
            None if row["visibility_value"] is None else int(row["visibility_value"])
        ),
        "property_ids": property_ids,
        "property_id": property_id,
        "property": None if property_id is None else propertydb.get(property_id),
        "properties": properties,
        "layers": _layers_from_properties(properties),
    }


def _point_from_core(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> Point:
    return Point(
        **_base_fields(row, raw_records), location=_vec_from_core(_mapping(row["location"]))
    )


def _property_from_core(row: Mapping[str, Any], raw_records: tuple[Any, ...]) -> Property:
    fields = {
        **_base_fields(row, raw_records),
        "values": tuple(bytes(value) for value in row["values"]),
    }
    part_status = row["part_status"]
    if part_status is not None:
        status = _mapping(part_status)
        return PartStatusProperty(
            **fields,
            shared=bool(status["shared"]),
            scale_modifiable=bool(status["scale_modifiable"]),
        )
    associated_strings = row["associated_strings"]
    if associated_strings is not None:
        return AssociatedStringsProperty(
            **fields,
            strings=tuple(_text_from_core(_mapping(value)) for value in associated_strings),
        )
    dimension_text_attribute = row["dimension_text_attribute"]
    if dimension_text_attribute is not None:
        value = _mapping(dimension_text_attribute)
        return DimensionTextAttributeProperty(
            **fields,
            font_name_value=_text_from_core(_mapping(value["font_name"])),
            alternate_font_name_value=_text_from_core(_mapping(value["alternate_font_name"])),
            symbol_font_name_value=_text_from_core(_mapping(value["symbol_font_name"])),
            definition_values=tuple(float(item) for item in value["definition_values"]),
        )
    integer_definition = row["integer_definition"]
    if integer_definition is not None:
        values = tuple(int(item) for item in integer_definition)
        if row["mi_type"] == "DTF":
            return DimensionTextFormatProperty(**fields, definition_values=values)
        if row["mi_type"] == "DDA":
            return DimensionDisplayAttributeProperty(**fields, definition_values=values)
        raise RuntimeError(f"unexpected integer property type: {row['mi_type']!r}")
    numeric_definition = row["numeric_definition"]
    if numeric_definition is not None:
        values = tuple(float(item) for item in numeric_definition)
        if row["mi_type"] == "DLA":
            return DimensionLineAttributeProperty(**fields, definition_values=values)
        if row["mi_type"] == "DAF":
            return DimensionArrowProperty(**fields, definition_values=values)
        raise RuntimeError(f"unexpected numeric property type: {row['mi_type']!r}")
    hatch_pattern = row["hatch_pattern"]
    if hatch_pattern is not None:
        return HatchPatternProperty(
            **fields,
            lines=tuple(
                HatchPatternLine(
                    offset=float(_mapping(item)["offset"]),
                    distance=float(_mapping(item)["distance"]),
                    angle=float(_mapping(item)["angle"]),
                    color=int(_mapping(item)["color"]),
                    linetype=int(_mapping(item)["linetype"]),
                )
                for item in hatch_pattern
            ),
        )
    return Property(**fields)


def _layers_from_properties(properties: tuple[Property, ...]) -> tuple[str, ...]:
    layers: list[str] = []
    for property_value in properties:
        if not isinstance(property_value, AssociatedStringsProperty):
            continue
        for string in property_value.strings:
            text = string.text
            if text is None or not text.startswith("LAYER:"):
                continue
            layer = text.partition(":")[2].strip()
            if layer and layer not in layers:
                layers.append(layer)
    return tuple(layers)


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


def _dimension_tolerance_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    propertydb: Mapping[int, Property],
) -> DimensionTolerance:
    text_style_id = int(row["text_style_id"])
    return DimensionTolerance(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
        definition_value=int(row["definition_value"]),
        upper_value=float(row["upper_value"]),
        lower_value=float(row["lower_value"]),
        format_value=int(row["format_value"]),
        upper_text_value=_text_from_core(_mapping(row["upper_text"])),
        lower_text_value=_text_from_core(_mapping(row["lower_text"])),
        text_style_id=text_style_id,
        text_style=propertydb.get(text_style_id),
        alignment=int(row["alignment"]),
    )


def _leader_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    propertydb: Mapping[int, Property],
) -> Leader:
    return Leader(
        **_graphic_fields(row, raw_records, propertydb),
        arrow_type=int(row["arrow_type"]),
        arrow_size=float(row["arrow_size"]),
        points=tuple(
            LeaderPoint(
                location=Vec2(x=float(_mapping(value)["x"]), y=float(_mapping(value)["y"])),
                elevation=float(_mapping(value)["z"]),
            )
            for value in row["points"]
        ),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _dimension_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    pointdb: Mapping[int, Point],
    graphicdb: Mapping[int, Graphic],
    propertydb: Mapping[int, Property],
    tolerancedb: Mapping[int, DimensionTolerance],
) -> Dimension:
    property_ids = tuple(int(value) for value in row["property_ids"])
    geometry_ids = tuple(int(value) for value in row["reference_geometry_ids"])
    point_ids = tuple(int(value) for value in row["reference_point_ids"])
    dimension_style_id = (
        None if row["dimension_style_id"] is None else int(row["dimension_style_id"])
    )
    text_style_id = None if row["text_style_id"] is None else int(row["text_style_id"])
    tolerance_ids = tuple(int(value) for value in row["tolerance_ids"])
    return Dimension(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
        property_ids=property_ids,
        properties=tuple(
            value
            for value in (propertydb.get(property_id) for property_id in property_ids)
            if value is not None
        ),
        reference_geometry_ids=geometry_ids,
        reference_geometries=tuple(graphicdb.get(entity_id) for entity_id in geometry_ids),
        reference_point_ids=point_ids,
        reference_points=tuple(pointdb.get(entity_id) for entity_id in point_ids),
        text_position=_vec_from_core(_mapping(row["text_position"])),
        measurement=float(row["measurement"]),
        formatted_text_value=_text_from_core(_mapping(row["formatted_text"])),
        dimension_style_id=dimension_style_id,
        dimension_style=(
            None if dimension_style_id is None else propertydb.get(dimension_style_id)
        ),
        text_style_id=text_style_id,
        text_style=None if text_style_id is None else propertydb.get(text_style_id),
        tolerance_ids=tolerance_ids,
        tolerances=tuple(tolerancedb.get(entity_id) for entity_id in tolerance_ids),
    )


def _contour_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    graphicdb: Mapping[int, Graphic],
    propertydb: Mapping[int, Property],
) -> Contour:
    component_ids = tuple(int(value) for value in row["component_ids"])
    return Contour(
        **_graphic_fields(row, raw_records, propertydb),
        closed=bool(row["closed"]),
        orientation=int(row["orientation"]),
        component_ids=component_ids,
        components=tuple(graphicdb.get(entity_id) for entity_id in component_ids),
        values=tuple(bytes(value) for value in row["values"]),
    )


def _symbol_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    graphicdb: Mapping[int, Graphic],
) -> Symbol:
    component_ids = tuple(int(value) for value in row["component_ids"])
    return Symbol(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
        component_ids=component_ids,
        components=tuple(graphicdb.get(entity_id) for entity_id in component_ids),
    )


def _hatch_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    contourdb: Mapping[int, Contour],
    propertydb: Mapping[int, Property],
) -> Hatch:
    graphic_fields = _graphic_fields(row, raw_records, propertydb)
    boundary_loop_ids = tuple(int(value) for value in row["boundary_loop_ids"])
    pattern = next(
        (
            value
            for value in graphic_fields["properties"]
            if isinstance(value, HatchPatternProperty)
        ),
        None,
    )
    return Hatch(
        **graphic_fields,
        reference_point=_vec_from_core(_mapping(row["reference_point"])),
        angle=float(row["angle"]),
        spacing=float(row["spacing"]),
        boundary_loop_ids=boundary_loop_ids,
        boundary_loops=tuple(contourdb.get(entity_id) for entity_id in boundary_loop_ids),
        pattern=pattern,
        values=tuple(bytes(value) for value in row["values"]),
    )


def _hatch_association_from_core(
    row: Mapping[str, Any],
    raw_records: tuple[Any, ...],
    hatchdb: Mapping[int, Hatch],
    contourdb: Mapping[int, Contour],
    propertydb: Mapping[int, Property],
) -> HatchAssociation:
    property_ids = tuple(int(value) for value in row["property_ids"])
    hatch_id = int(row["hatch_id"])
    outer_loop_id = int(row["outer_loop_id"])
    inner_loop_ids = tuple(int(value) for value in row["inner_loop_ids"])
    return HatchAssociation(
        **_base_fields(row, raw_records),
        values=tuple(bytes(value) for value in row["values"]),
        property_ids=property_ids,
        properties=tuple(
            value
            for value in (propertydb.get(property_id) for property_id in property_ids)
            if value is not None
        ),
        hatch_id=hatch_id,
        hatch=hatchdb.get(hatch_id),
        outer_loop_id=outer_loop_id,
        outer_loop=contourdb.get(outer_loop_id),
        inner_loop_ids=inner_loop_ids,
        inner_loops=tuple(contourdb.get(entity_id) for entity_id in inner_loop_ids),
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
        prefix_values=tuple(bytes(value) for value in row["prefix_values"]),
        center_id=center_id,
        start_id=start_id,
        end_id=end_id,
        orientation=int(row["orientation"]),
        ccw=None if row["ccw"] is None else bool(row["ccw"]),
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
        prefix_values=tuple(bytes(value) for value in row["prefix_values"]),
        center_id=center_id,
        start_id=start_id,
        end_id=end_id,
        orientation=int(row["orientation"]),
        ccw=None if row["ccw"] is None else bool(row["ccw"]),
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
        closed=None if row["closed"] is None else bool(row["closed"]),
        periodic=None if row["periodic"] is None else bool(row["periodic"]),
        rational=None if row["rational"] is None else bool(row["rational"]),
        weights=(
            None if row["weights"] is None else tuple(float(value) for value in row["weights"])
        ),
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
        alignment=int(row["alignment"]),
        transform_values=transform_values,
        origin=_vec_from_core(_mapping(row["origin"])),
        rotation=float(row["rotation"]),
        width_factor=float(row["width_factor"]),
        mirrored=bool(row["mirrored"]),
        font_name_value=_text_from_core(_mapping(row["font_name"])),
        alternate_font_name_value=_optional_text(row["alternate_font_name"]),
        size_values=cast(tuple[float, float], size_values),
        height=float(row["height"]),
        line_spacing=float(row["line_spacing"]),
        line_values=tuple(_text_from_core(_mapping(value)) for value in row["lines"]),
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
        contours=tuple(entity for entity in source_entities if isinstance(entity, Contour)),
        hatch_associations=tuple(
            entity for entity in source_entities if isinstance(entity, HatchAssociation)
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
