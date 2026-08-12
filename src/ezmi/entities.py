"""Typed entities for the verified legacy MI geometry and text subset."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, TypeAlias

from .raw import RawRecord


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float

    def distance_to(self, other: Vec2) -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True, slots=True)
class Bounds2:
    min: Vec2
    max: Vec2

    @property
    def width(self) -> float:
        return self.max.x - self.min.x

    @property
    def height(self) -> float:
        return self.max.y - self.min.y


@dataclass(frozen=True, slots=True)
class TextValue:
    """Raw text bytes plus a strictly decoded value when its encoding is known."""

    raw_bytes: bytes
    text: str | None
    encoding: str | None


@dataclass(frozen=True, slots=True)
class MiEntity:
    id: int
    mi_type: str
    raw_record: RawRecord
    part_index: int | None


@dataclass(frozen=True, slots=True)
class Point(MiEntity):
    KIND: ClassVar[str] = "P"
    location: Vec2


@dataclass(frozen=True, slots=True)
class Property(MiEntity):
    """A minimally decoded PSTAT/ASSP property record."""

    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class Assembly(MiEntity):
    property_ids: tuple[int, ...]
    part_name_value: TextValue | None
    instances: tuple[AssemblyInstance, ...]
    definition_part_index: int | None
    values: tuple[bytes, ...]

    @property
    def part_name(self) -> str | None:
        return None if self.part_name_value is None else self.part_name_value.text

    @property
    def part_name_bytes(self) -> bytes | None:
        return None if self.part_name_value is None else self.part_name_value.raw_bytes


@dataclass(frozen=True, slots=True)
class UnsupportedEntity(MiEntity):
    """Addressable MI entity retained through its Phase 1 raw record."""


@dataclass(frozen=True, slots=True)
class GraphicEntity(MiEntity):
    """Legacy display fields; modern variable-prefix records expose ``None``."""

    display_values: tuple[int, int, int, int] | None
    property_id: int | None
    property: Property | None


@dataclass(frozen=True, slots=True)
class Line(GraphicEntity):
    KIND: ClassVar[str] = "LIN"
    start_id: int
    end_id: int
    start_point: Point | None
    end_point: Point | None

    @property
    def start(self) -> Vec2 | None:
        return None if self.start_point is None else self.start_point.location

    @property
    def end(self) -> Vec2 | None:
        return None if self.end_point is None else self.end_point.location


@dataclass(frozen=True, slots=True)
class Arc(GraphicEntity):
    """Resolved arc whose derived angles are radians normalized to ``[0, 2π)``."""

    KIND: ClassVar[str] = "ARC"
    center_id: int
    start_id: int
    end_id: int
    orientation: int
    center_point: Point | None
    start_point: Point | None
    end_point: Point | None
    radius: float | None
    start_angle: float | None
    end_angle: float | None

    @property
    def center(self) -> Vec2 | None:
        return None if self.center_point is None else self.center_point.location

    @property
    def start(self) -> Vec2 | None:
        return None if self.start_point is None else self.start_point.location

    @property
    def end(self) -> Vec2 | None:
        return None if self.end_point is None else self.end_point.location


@dataclass(frozen=True, slots=True)
class Fillet(Arc):
    """Legacy FIL geometry, verified as an arc against the paired DXF corpus."""

    KIND: ClassVar[str] = "FIL"


@dataclass(frozen=True, slots=True)
class BSplineSample:
    point_id: int
    parameter: float
    definition_values: tuple[float, float, float, float, float]
    point: Point | None


@dataclass(frozen=True, slots=True)
class BSpline(GraphicEntity):
    """Non-rational B-spline with a corpus-verified control-point/knot layout."""

    KIND: ClassVar[str] = "BSPL"
    prefix_values: tuple[bytes, ...]
    order: int
    degree: int
    definition_values: tuple[bytes, bytes]
    parameter_max: float
    parameter_domain: tuple[float, float]
    start_id: int
    end_id: int
    start_point: Point | None
    end_point: Point | None
    control_point_ids: tuple[int, ...]
    control_points: tuple[Point | None, ...]
    knots: tuple[float, ...]
    samples: tuple[BSplineSample, ...]
    values: tuple[bytes, ...]

    @property
    def start(self) -> Vec2 | None:
        return None if self.start_point is None else self.start_point.location

    @property
    def end(self) -> Vec2 | None:
        return None if self.end_point is None else self.end_point.location

    def evaluate(self, parameter: float) -> Vec2:
        """Evaluate the curve with De Boor's algorithm."""

        if not math.isfinite(parameter):
            raise ValueError("B-spline parameter must be finite")
        domain_start, domain_end = self.parameter_domain
        if parameter < domain_start or parameter > domain_end:
            raise ValueError(
                f"B-spline parameter {parameter} is outside [{domain_start}, {domain_end}]"
            )
        if any(point is None for point in self.control_points):
            raise LookupError("B-spline has unresolved control points")
        points = [point.location for point in self.control_points if point is not None]
        last = len(points) - 1
        if parameter == domain_end:
            knot_span = last
        else:
            knot_span = next(
                index
                for index in range(self.degree, last + 1)
                if self.knots[index] <= parameter < self.knots[index + 1]
            )
        work = [points[knot_span - self.degree + offset] for offset in range(self.degree + 1)]
        for level in range(1, self.degree + 1):
            for offset in range(self.degree, level - 1, -1):
                knot_index = knot_span - self.degree + offset
                denominator = (
                    self.knots[knot_index + self.degree - level + 1] - self.knots[knot_index]
                )
                alpha = (
                    0.0
                    if denominator == 0.0
                    else (parameter - self.knots[knot_index]) / denominator
                )
                work[offset] = Vec2(
                    (1.0 - alpha) * work[offset - 1].x + alpha * work[offset].x,
                    (1.0 - alpha) * work[offset - 1].y + alpha * work[offset].y,
                )
        return work[-1]


@dataclass(frozen=True, slots=True)
class Circle(GraphicEntity):
    KIND: ClassVar[str] = "CIR"
    center_id: int
    circumference_id: int
    center_point: Point | None
    circumference_point: Point | None
    radius: float | None

    @property
    def center(self) -> Vec2 | None:
        return None if self.center_point is None else self.center_point.location

    @property
    def circumference(self) -> Vec2 | None:
        return None if self.circumference_point is None else self.circumference_point.location


@dataclass(frozen=True, slots=True)
class Text(GraphicEntity):
    """Legacy TEX subset verified against the paired MI/DXF corpus."""

    KIND: ClassVar[str] = "TEX"
    transform_values: tuple[float, ...]
    origin: Vec2
    font_name_value: TextValue
    size_values: tuple[float, float]
    height: float
    content_value: TextValue
    values: tuple[bytes, ...]

    @property
    def text(self) -> str | None:
        return self.content_value.text

    @property
    def text_bytes(self) -> bytes:
        return self.content_value.raw_bytes

    @property
    def font_name(self) -> str | None:
        return self.font_name_value.text

    @property
    def font_name_bytes(self) -> bytes:
        return self.font_name_value.raw_bytes


@dataclass(frozen=True, slots=True)
class StructuredEntity(MiEntity):
    """Typed record family whose version-specific fields remain lossless bytes."""

    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class Dimension(StructuredEntity):
    pass


@dataclass(frozen=True, slots=True)
class DimensionTolerance(StructuredEntity):
    pass


@dataclass(frozen=True, slots=True)
class Leader(StructuredEntity):
    pass


@dataclass(frozen=True, slots=True)
class Hatch(StructuredEntity):
    pass


@dataclass(frozen=True, slots=True)
class Symbol(StructuredEntity):
    pass


@dataclass(frozen=True, slots=True)
class AssemblyInstance:
    relation_value: bytes | None
    definition_values: tuple[bytes, bytes, bytes]
    member_ids: tuple[int, ...]
    assembly_id: int
    transform_values: tuple[float, ...]
    target_part_index: int | None
    is_sheet: bool


Graphic: TypeAlias = Line | Arc | Fillet | BSpline | Circle | Text
Annotation: TypeAlias = Dimension | DimensionTolerance | Leader | Hatch | Symbol
AddressableEntity: TypeAlias = (
    Point | Graphic | Annotation | Property | Assembly | UnsupportedEntity
)


def query_entities(entities: tuple[Graphic, ...], query: str = "*") -> tuple[Graphic, ...]:
    """Select graphic entities by whitespace/comma-separated MI or common names."""

    normalized = query.replace(",", " ").strip().upper()
    if not normalized or normalized == "*":
        return entities
    aliases = {
        "LIN": "LIN",
        "LINE": "LIN",
        "ARC": "ARC",
        "FIL": "FIL",
        "FILLET": "FIL",
        "BSPL": "BSPL",
        "BSPLINE": "BSPL",
        "SPLINE": "BSPL",
        "CIR": "CIR",
        "CIRCLE": "CIR",
        "TEX": "TEX",
        "TEXT": "TEX",
    }
    requested: set[str] = set()
    for token in normalized.split():
        try:
            requested.add(aliases[token])
        except KeyError as error:
            raise ValueError(f"unsupported MI entity query type: {token}") from error
    return tuple(entity for entity in entities if entity.mi_type in requested)


def query_annotation_entities(
    entities: tuple[Annotation, ...], query: str = "*"
) -> tuple[Annotation, ...]:
    """Select annotation records by MI type or common family name."""

    normalized = query.replace(",", " ").strip().upper()
    if not normalized or normalized == "*":
        return entities
    aliases = {
        "DANG": {"DANG"},
        "DCHMF": {"DCHMF"},
        "DDIA": {"DDIA"},
        "DRAD": {"DRAD"},
        "DSGL": {"DSGL"},
        "DIMENSION": {"DANG", "DCHMF", "DDIA", "DRAD", "DSGL"},
        "DTV": {"DTV"},
        "TOLERANCE": {"DTV"},
        "LED": {"LED"},
        "LEADER": {"LED"},
        "HAT": {"HAT"},
        "HATCH": {"HAT"},
        "SYML": {"SYML"},
        "SYMBOL": {"SYML"},
    }
    requested: set[str] = set()
    for token in normalized.split():
        try:
            requested.update(aliases[token])
        except KeyError as error:
            raise ValueError(f"unsupported MI annotation query type: {token}") from error
    return tuple(entity for entity in entities if entity.mi_type in requested)
