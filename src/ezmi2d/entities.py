"""Typed entities for the verified legacy MI geometry and text subset."""

from __future__ import annotations

import math
from collections.abc import Sequence
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
class Affine2D:
    """Canonical child-to-parent 2D affine transform.

    Points are column vectors and are mapped as
    ``x' = a*x + c*y + tx`` and ``y' = b*x + d*y + ty``. The equivalent
    row-major matrix is ``(a, c, tx, b, d, ty, 0, 0, 1)``.
    """

    a: float
    b: float
    c: float
    d: float
    tx: float
    ty: float

    def __post_init__(self) -> None:
        for name in ("a", "b", "c", "d", "tx", "ty"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"Affine2D.{name} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"Affine2D.{name} must be finite")

    @classmethod
    def identity(cls) -> Affine2D:
        return cls(a=1.0, b=0.0, c=0.0, d=1.0, tx=0.0, ty=0.0)

    @classmethod
    def from_transform_values(cls, values: Sequence[float]) -> Affine2D:
        """Decode MI's serialized row-major 3x3 child-to-parent matrix."""

        if len(values) != 9:
            raise ValueError(f"affine transform has {len(values)} values; expected 9")
        matrix = tuple(float(value) for value in values)
        if not all(math.isfinite(value) for value in matrix):
            raise ValueError("affine transform values must be finite")
        if not (
            math.isclose(matrix[6], 0.0, abs_tol=1e-12)
            and math.isclose(matrix[7], 0.0, abs_tol=1e-12)
            and math.isclose(matrix[8], 1.0, abs_tol=1e-12)
        ):
            raise ValueError(
                "MI transform is not affine: the final row must be approximately (0, 0, 1)"
            )
        return cls(
            a=matrix[0],
            b=matrix[3],
            c=matrix[1],
            d=matrix[4],
            tx=matrix[2],
            ty=matrix[5],
        )

    def to_transform_values(self) -> tuple[float, ...]:
        """Return the canonical row-major 3x3 serialization."""

        return (self.a, self.c, self.tx, self.b, self.d, self.ty, 0.0, 0.0, 1.0)

    def transform_point(self, point: Vec2) -> Vec2:
        return Vec2(
            self.a * point.x + self.c * point.y + self.tx,
            self.b * point.x + self.d * point.y + self.ty,
        )

    def transform_vector(self, vector: Vec2) -> Vec2:
        return Vec2(
            self.a * vector.x + self.c * vector.y,
            self.b * vector.x + self.d * vector.y,
        )

    def compose(self, other: Affine2D) -> Affine2D:
        """Return ``self ∘ other`` (apply ``other`` first, then ``self``)."""

        if not isinstance(other, Affine2D):
            raise TypeError("other must be an Affine2D")
        return Affine2D(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            tx=self.a * other.tx + self.c * other.ty + self.tx,
            ty=self.b * other.tx + self.d * other.ty + self.ty,
        )

    @property
    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c

    @property
    def is_mirrored(self) -> bool:
        return self.determinant < 0.0

    def inverse(self) -> Affine2D:
        determinant = self.determinant
        if math.isclose(determinant, 0.0, abs_tol=1e-15):
            raise ValueError("affine transform is singular")
        return Affine2D(
            a=self.d / determinant,
            b=-self.b / determinant,
            c=-self.c / determinant,
            d=self.a / determinant,
            tx=(self.c * self.ty - self.d * self.tx) / determinant,
            ty=(self.b * self.tx - self.a * self.ty) / determinant,
        )


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
    """A source-level MI property record with lossless fallback values."""

    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class PartStatusProperty(Property):
    """PSTAT part-sharing and scale-modification flags."""

    shared: bool
    scale_modifiable: bool


@dataclass(frozen=True, slots=True)
class AssociatedStringsProperty(Property):
    """ASSP strings attached to an entity or part."""

    strings: tuple[TextValue, ...]


@dataclass(frozen=True, slots=True)
class DimensionTextAttributeProperty(Property):
    """DTA font fields plus version-specific numeric definition values."""

    font_name_value: TextValue
    alternate_font_name_value: TextValue
    symbol_font_name_value: TextValue
    definition_values: tuple[float, ...]

    @property
    def font_name(self) -> str | None:
        return self.font_name_value.text

    @property
    def alternate_font_name(self) -> str | None:
        return self.alternate_font_name_value.text

    @property
    def symbol_font_name(self) -> str | None:
        return self.symbol_font_name_value.text


@dataclass(frozen=True, slots=True)
class DimensionTextFormatProperty(Property):
    """DTF integer definition table; enumeration meanings remain version-specific."""

    definition_values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DimensionDisplayAttributeProperty(Property):
    """DDA integer definition table; enumeration meanings remain version-specific."""

    definition_values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DimensionLineAttributeProperty(Property):
    """DLA numeric definition table retained in serialized order."""

    definition_values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DimensionArrowProperty(Property):
    """DAF numeric arrow definition table retained in serialized order."""

    definition_values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class HatchPatternLine:
    """One HAPP sub-pattern in source order."""

    offset: float
    distance: float
    angle: float
    color: int
    linetype: int


@dataclass(frozen=True, slots=True)
class HatchPatternProperty(Property):
    """HAPP pattern made from one or more simple hatch lines."""

    lines: tuple[HatchPatternLine, ...]


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
    """Source graphic attributes plus resolved attached properties."""

    display_values: tuple[int, int, int, int] | None
    color: int
    linetype: int
    lineweight: float
    visibility: bool | None
    visibility_value: int | None
    property_ids: tuple[int, ...]
    property_id: int | None
    property: Property | None
    properties: tuple[Property, ...]
    layers: tuple[str, ...]

    @property
    def layer(self) -> str | None:
        """Return the sole attached layer, or ``None`` when absent/ambiguous."""

        return self.layers[0] if len(self.layers) == 1 else None

    @property
    def color_name(self) -> str | None:
        return {
            0: "black",
            1: "red",
            2: "green",
            3: "yellow",
            4: "blue",
            5: "magenta",
            6: "cyan",
            7: "white",
        }.get(self.color)

    @property
    def linetype_name(self) -> str | None:
        return {
            0: "solid",
            1: "dashed",
            2: "dotted",
            3: "dot_center",
            4: "dash_dot_dot",
            5: "long_dashed",
            6: "dash_center",
            7: "phantom",
            8: "legacy_phantom",
            9: "short_dash",
            10: "center_dash_dash",
            11: "long_dash_short_dash",
            12: "long_dash_two_short_dash",
        }.get(self.linetype)


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
    prefix_values: tuple[bytes, ...]
    center_id: int
    start_id: int
    end_id: int
    orientation: int
    ccw: bool | None
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
    """B-spline with a corpus-verified control-point/knot layout."""

    KIND: ClassVar[str] = "BSPL"
    prefix_values: tuple[bytes, ...]
    order: int
    degree: int
    definition_values: tuple[bytes, bytes]
    closed: bool | None
    periodic: bool | None
    rational: bool | None
    weights: tuple[float, ...] | None
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
        if self.rational is True:
            if self.weights is None:
                raise LookupError("rational B-spline has no recorded control-point weights")
            if len(self.weights) != len(points):
                raise ValueError(
                    f"B-spline has {len(points)} control points but {len(self.weights)} weights"
                )
            if not all(math.isfinite(weight) for weight in self.weights):
                raise ValueError("B-spline weights must be finite")
            homogeneous = [
                (point.x * weight, point.y * weight, weight)
                for point, weight in zip(points, self.weights, strict=True)
            ]
        else:
            homogeneous = [(point.x, point.y, 1.0) for point in points]
        work = [homogeneous[knot_span - self.degree + offset] for offset in range(self.degree + 1)]
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
                work[offset] = (
                    (1.0 - alpha) * work[offset - 1][0] + alpha * work[offset][0],
                    (1.0 - alpha) * work[offset - 1][1] + alpha * work[offset][1],
                    (1.0 - alpha) * work[offset - 1][2] + alpha * work[offset][2],
                )
        x, y, weight = work[-1]
        if math.isclose(weight, 0.0, abs_tol=1e-15):
            raise ValueError("rational B-spline evaluates to a zero homogeneous weight")
        return Vec2(x / weight, y / weight)


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
    alignment: int
    transform_values: tuple[float, ...]
    origin: Vec2
    rotation: float
    width_factor: float
    mirrored: bool
    font_name_value: TextValue
    alternate_font_name_value: TextValue | None
    size_values: tuple[float, float]
    height: float
    line_spacing: float
    line_values: tuple[TextValue, ...]
    content_value: TextValue
    values: tuple[bytes, ...]

    @property
    def transform(self) -> Affine2D:
        return Affine2D.from_transform_values(self.transform_values)

    @property
    def horizontal_alignment(self) -> str:
        return ("left", "center", "right")[(self.alignment - 1) % 3]

    @property
    def vertical_alignment(self) -> str:
        return ("lower", "middle", "upper")[(self.alignment - 1) // 3]

    @property
    def mirror(self) -> bool:
        return self.mirrored

    @property
    def lines(self) -> tuple[str | None, ...]:
        return tuple(line.text for line in self.line_values)

    @property
    def text(self) -> str | None:
        if any(line.text is None for line in self.line_values):
            return None
        return "\n".join(line.text for line in self.line_values if line.text is not None)

    @property
    def text_bytes(self) -> bytes:
        return b"\n".join(line.raw_bytes for line in self.line_values)

    @property
    def font_name(self) -> str | None:
        return self.font_name_value.text

    @property
    def font_name_bytes(self) -> bytes:
        return self.font_name_value.raw_bytes

    @property
    def alternate_font_name(self) -> str | None:
        if self.alternate_font_name_value is None:
            return None
        return self.alternate_font_name_value.text


@dataclass(frozen=True, slots=True)
class StructuredEntity(MiEntity):
    """Typed record family whose version-specific fields remain lossless bytes."""

    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class Dimension(StructuredEntity):
    property_ids: tuple[int, ...]
    properties: tuple[Property, ...]
    reference_geometry_ids: tuple[int, ...]
    reference_geometries: tuple[Graphic | None, ...]
    reference_point_ids: tuple[int, ...]
    reference_points: tuple[Point | None, ...]
    text_position: Vec2
    measurement: float
    formatted_text_value: TextValue
    dimension_style_id: int | None
    dimension_style: Property | None
    text_style_id: int | None
    text_style: Property | None
    tolerance_ids: tuple[int, ...]
    tolerances: tuple[DimensionTolerance | None, ...]

    @property
    def formatted_text(self) -> str | None:
        return self.formatted_text_value.text

    @property
    def formatted_text_bytes(self) -> bytes:
        return self.formatted_text_value.raw_bytes


@dataclass(frozen=True, slots=True)
class DimensionTolerance(StructuredEntity):
    definition_value: int
    upper_value: float
    lower_value: float
    format_value: int
    upper_text_value: TextValue
    lower_text_value: TextValue
    text_style_id: int
    text_style: Property | None
    alignment: int

    @property
    def upper_text(self) -> str | None:
        return self.upper_text_value.text

    @property
    def lower_text(self) -> str | None:
        return self.lower_text_value.text

    @property
    def horizontal_alignment(self) -> str:
        return ("left", "center", "right")[(self.alignment - 1) % 3]

    @property
    def vertical_alignment(self) -> str:
        return ("lower", "middle", "upper")[(self.alignment - 1) // 3]


@dataclass(frozen=True, slots=True)
class LeaderPoint:
    location: Vec2
    elevation: float


@dataclass(frozen=True, slots=True)
class Leader(GraphicEntity):
    arrow_type: int
    arrow_size: float
    points: tuple[LeaderPoint, ...]
    values: tuple[bytes, ...]

    @property
    def vertices(self) -> tuple[Vec2, ...]:
        return tuple(point.location for point in self.points)


@dataclass(frozen=True, slots=True)
class Contour(GraphicEntity):
    """COC ordered composite curve used by associative hatch boundaries."""

    closed: bool
    orientation: int
    component_ids: tuple[int, ...]
    components: tuple[Graphic | None, ...]
    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class Hatch(GraphicEntity):
    reference_point: Vec2
    angle: float
    spacing: float
    boundary_loop_ids: tuple[int, ...]
    boundary_loops: tuple[Contour | None, ...]
    pattern: HatchPatternProperty | None
    values: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class HatchAssociation(StructuredEntity):
    """PFA association linking one HAT to its outer and inner COC loops."""

    property_ids: tuple[int, ...]
    properties: tuple[Property, ...]
    hatch_id: int
    hatch: Hatch | None
    outer_loop_id: int
    outer_loop: Contour | None
    inner_loop_ids: tuple[int, ...]
    inner_loops: tuple[Contour | None, ...]


@dataclass(frozen=True, slots=True)
class Symbol(StructuredEntity):
    component_ids: tuple[int, ...]
    components: tuple[Graphic | None, ...]


@dataclass(frozen=True, slots=True)
class AssemblyInstance:
    relation_value: bytes | None
    definition_values: tuple[bytes, bytes, bytes]
    member_ids: tuple[int, ...]
    assembly_id: int
    transform_values: tuple[float, ...]
    target_part_index: int | None
    is_sheet: bool

    def to_affine2d(self) -> Affine2D:
        """Return this instance's child-to-parent transform."""

        return Affine2D.from_transform_values(self.transform_values)


Graphic: TypeAlias = Line | Arc | Fillet | BSpline | Circle | Text
Annotation: TypeAlias = Dimension | DimensionTolerance | Leader | Hatch | Symbol
AddressableEntity: TypeAlias = (
    Point
    | Graphic
    | Annotation
    | Contour
    | HatchAssociation
    | Property
    | Assembly
    | UnsupportedEntity
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
