"""Typed entities for the verified legacy MI geometry and text subset."""

from __future__ import annotations

import math
import re
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
    """DTA text attribute of a dimension or tolerance text: fonts and text size.

    ``size`` is the third numeric value: the character height in drawing units, or,
    when ``relative_size`` is true (the second numeric value is 1), a factor of the
    main text of the dimension (0.6 for a tolerance at 60 %). Both are ``None`` when
    the record does not state them. The other numeric values stay in
    ``definition_values``; their meanings vary by MI version.
    """

    font_name_value: TextValue
    alternate_font_name_value: TextValue
    symbol_font_name_value: TextValue
    definition_values: tuple[float, ...]
    size: float | None = None
    relative_size: bool | None = None

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
    """DAF definition of a dimension terminator, retained in serialized order.

    The five values are the shape code, the filling code, whether the sizes are
    factors of the main text of the dimension (1) or lengths (0), the length of the
    terminator and its width. Shape 1 is stored with a width of 0.26 of the length
    and shape 5 with 0.54, a 15 and a 30 degree arrowhead; the other shape codes and
    the filling code are not established.
    """

    definition_values: tuple[float, ...]

    def _value(self, index: int) -> float | None:
        values = self.definition_values
        return values[index] if len(values) == 5 else None

    @property
    def shape_value(self) -> int | None:
        value = self._value(0)
        return int(value) if value is not None and value == int(value) else None

    @property
    def filling_value(self) -> int | None:
        value = self._value(1)
        return int(value) if value is not None and value == int(value) else None

    @property
    def relative_size(self) -> bool | None:
        value = self._value(2)
        return {0.0: False, 1.0: True}.get(value) if value is not None else None

    def length(self, main_text_height: float | None = None) -> float | None:
        """Length of the terminator from its tip, in drawing units."""
        return self._length(3, main_text_height)

    def width(self, main_text_height: float | None = None) -> float | None:
        """Width of the terminator at its far end, in drawing units."""
        return self._length(4, main_text_height)

    def _length(self, index: int, main_text_height: float | None) -> float | None:
        value = self._value(index)
        if value is None or not value > 0.0:
            return None
        if self.relative_size is False:
            return value
        if self.relative_size is True and main_text_height is not None:
            return value * main_text_height
        return None


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
    """ASSE record of one part: its name, scale and offset, and the parts it places.

    A point of the part is drawn at ``scale * point + offset`` in sheet coordinates,
    whatever part it is placed in. ``scale`` and ``offset`` are ``None`` for legacy
    records, which do not write them, and when the written scale is not a positive number.
    """

    property_ids: tuple[int, ...]
    part_name_value: TextValue | None
    instances: tuple[AssemblyInstance, ...]
    definition_part_index: int | None
    values: tuple[bytes, ...]
    scale: float | None = None
    offset: Vec2 | None = None

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
class DimensionArrow:
    """A terminator stored with a dimension."""

    #: 1 for a terminator that is drawn, 0 for one stored without being drawn.
    display_value: int
    style_id: int
    style: Property | None
    tip: Vec2
    #: Direction from the tip along the body of the terminator, in radians.
    angle: float

    @property
    def visible(self) -> bool:
        return self.display_value == 1

    def outline(self, main_text_height: float | None = None) -> tuple[Vec2, Vec2, Vec2] | None:
        """The arrowhead as a triangle: one corner of the far end, the tip, the other.

        ``None`` for a shape other than the two arrowheads (shape codes 1 and 5) or
        when the size cannot be told.
        """
        style = self.style
        if not isinstance(style, DimensionArrowProperty) or style.shape_value not in (1, 5):
            return None
        length = style.length(main_text_height)
        width = style.width(main_text_height)
        if length is None or width is None:
            return None
        along = Vec2(math.cos(self.angle), math.sin(self.angle))
        back = Vec2(self.tip.x + along.x * length, self.tip.y + along.y * length)
        half = width / 2.0
        return (
            Vec2(back.x - along.y * half, back.y + along.x * half),
            self.tip,
            Vec2(back.x + along.y * half, back.y - along.x * half),
        )


@dataclass(frozen=True, slots=True)
class DimensionSegment:
    """A straight piece of a dimension line or of an extension line."""

    start: Vec2
    end: Vec2


@dataclass(frozen=True, slots=True)
class DimensionArc:
    """A piece of a dimension arc, counterclockwise from ``start`` to ``end``."""

    start: Vec2
    end: Vec2
    center: Vec2

    @property
    def radius(self) -> float:
        return self.center.distance_to(self.start)

    @property
    def start_angle(self) -> float:
        return math.atan2(self.start.y - self.center.y, self.start.x - self.center.x)

    @property
    def sweep(self) -> float:
        """Angle covered from ``start`` to ``end`` in radians, between 0 and 2 pi."""
        end = math.atan2(self.end.y - self.center.y, self.end.x - self.center.x)
        return (end - self.start_angle) % math.tau


@dataclass(frozen=True, slots=True)
class DimensionTextPart:
    """A text beside the main text of a dimension."""

    #: Which of the five text lists of the record holds the text, from 0.
    slot: int
    text_value: TextValue
    #: Start of the text: the lower left corner of its first character.
    origin: Vec2
    text_attribute_id: int
    text_attribute: Property | None

    @property
    def text(self) -> str | None:
        return self.text_value.text

    @property
    def role(self) -> str | None:
        """``"prefix"`` (before the main text), ``"postfix"`` (after it) or
        ``"subfix"`` (in a row below it); ``None`` for a list whose use is not known.
        """
        return {1: "prefix", 2: "postfix", 4: "subfix"}.get(self.slot)

    def text_height(self, main_text_height: float | None = None) -> float | None:
        return _attribute_text_height(self.text_attribute, main_text_height)


@dataclass(frozen=True, slots=True)
class DimensionTolerancePlacement:
    """Where the texts of a tolerance are drawn."""

    #: 1: one text after the main text. 2: an upper and a lower text after the main
    #: text. 3: two limits drawn in place of the main text.
    layout_value: int
    tolerance_id: int
    tolerance: DimensionTolerance | None
    upper_origin: Vec2
    #: Start of the lower text; layout 1 has none and stores the text position here.
    lower_origin: Vec2

    @property
    def replaces_main_text(self) -> bool:
        return self.layout_value == 3


@dataclass(frozen=True, slots=True)
class DimensionGraphics:
    """The drawn form of a dimension as the file stores it.

    The file keeps these coordinates relative to the text position, without
    rotation. Here the text position is added, so they are in the coordinate system
    of the part like every other entity. Every text starts at the lower left corner
    of its first character and runs along ``Dimension.text_rotation``.
    """

    text_origin: Vec2
    #: Value after the start of the main text: 0 or 1; its meaning is not established.
    text_flag_value: int
    tolerance: DimensionTolerancePlacement | None
    arrows: tuple[DimensionArrow, ...]
    line_style_id: int
    line_style: Property | None
    lines: tuple[DimensionSegment, ...]
    extension_lines: tuple[DimensionSegment, ...]
    arcs: tuple[DimensionArc, ...]
    text_parts: tuple[DimensionTextPart, ...]


#: Characters of the symbol font (``hp_symbols``) a dimension text switches to. A
#: UTF-8 file (MI 3.40) writes them as U+E000 plus the code; an older file writes
#: the code between the control characters SO (0x0E) and SI (0x0F). Codes 0, 1 and
#: 2 stand where a degree sign (every angular dimension), a diameter sign (the
#: prefix of a diameter) and a plus-minus sign (a tolerance with one text) belong;
#: with 3 and 4 as minutes and seconds the parts of an angle add up to its
#: measurement. Minutes and seconds become the apostrophe and the quotation mark,
#: the way CAD texts write them and every character set has them.
_SYMBOL_FONT_CHARACTERS = {
    "0": "\u00b0",
    "1": "\u2300",
    "2": "\u00b1",
    "3": "'",
    "4": '"',
}
_SYMBOL_ESCAPE = re.compile("\x0e([^\x0e\x0f]*)\x0f")


def replace_symbol_codes(text: str) -> str:
    """Replace the symbol font codes of a dimension text by the characters they draw.

    ``"60\\ue030"`` and ``"60\\x0e0\\x0f"`` both become ``"60°"``. A code that is
    not known is left as it is, an escape with one in it as a whole.
    """

    def escape(match: re.Match[str]) -> str:
        codes = match.group(1)
        if all(code in _SYMBOL_FONT_CHARACTERS for code in codes):
            return "".join(_SYMBOL_FONT_CHARACTERS[code] for code in codes)
        return match.group(0)

    if "\x0e" in text:
        text = _SYMBOL_ESCAPE.sub(escape, text)
    if any("\ue000" <= character <= "\ue0ff" for character in text):
        text = "".join(
            _SYMBOL_FONT_CHARACTERS.get(chr(ord(character) - 0xE000), character)
            if "\ue000" <= character <= "\ue0ff"
            else character
            for character in text
        )
    return text


def _attribute_text_height(
    attribute: Property | None, main_text_height: float | None
) -> float | None:
    if not isinstance(attribute, DimensionTextAttributeProperty) or attribute.size is None:
        return None
    if attribute.relative_size is False:
        return attribute.size
    if attribute.relative_size is True and main_text_height is not None:
        return attribute.size * main_text_height
    return None


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
    #: Pointer to the DTA text attribute (fonts and size) of the main text.
    text_attribute_id: int | None = None
    text_attribute: Property | None = None
    #: Extent of the stored text box along the text (direction of the text, length =
    #: width of the box, tolerances included) and across it (length = height of the
    #: box). The text position is the middle of the box.
    text_extent: Vec2 = Vec2(0.0, 0.0)
    text_up_extent: Vec2 = Vec2(0.0, 0.0)
    #: The drawn form stored after the formatted text: where each text starts, the
    #: terminators and the line pieces. ``None`` when those fields do not follow the
    #: layout read from MI 2.40 through 3.40.
    graphics: DimensionGraphics | None = None

    @property
    def formatted_text(self) -> str | None:
        return self.formatted_text_value.text

    @property
    def formatted_text_bytes(self) -> bytes:
        return self.formatted_text_value.raw_bytes

    @property
    def text_height(self) -> float | None:
        """Character height of the main text in drawing units.

        The size of the DTA text attribute the dimension points to. ``None`` when the
        dimension names no such attribute or the attribute states a factor instead of
        a length.
        """
        attribute = self.text_attribute
        if not isinstance(attribute, DimensionTextAttributeProperty):
            return None
        if attribute.size is None or attribute.relative_size is not False:
            return None
        return attribute.size

    @property
    def text_rotation(self) -> float | None:
        """Direction of the text in radians, from the stored text box.

        ``None`` when the box has no extent along the text.
        """
        if self.text_extent.x == 0.0 and self.text_extent.y == 0.0:
            return None
        return math.atan2(self.text_extent.y, self.text_extent.x)


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
    #: Pointer to the DTA text attribute (fonts and size) of the tolerance text: the
    #: last field of the record.
    text_attribute_id: int
    text_attribute: Property | None = None

    @property
    def upper_text(self) -> str | None:
        return self.upper_text_value.text

    @property
    def lower_text(self) -> str | None:
        return self.lower_text_value.text

    @property
    def alignment(self) -> int:
        """Deprecated: the last field of the record, which is ``text_attribute_id``.

        Earlier versions read it as a text alignment code of 1 through 9. In every
        tolerance of the corpus it is the ID of a DTA record.
        """
        return self.text_attribute_id

    def text_height(self, main_text_height: float | None = None) -> float | None:
        """Character height of the tolerance text in drawing units.

        A text attribute with a relative size is a factor of the main text of the
        dimension, passed as ``main_text_height``. ``None`` when it cannot be told.
        """
        return _attribute_text_height(self.text_attribute, main_text_height)


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
