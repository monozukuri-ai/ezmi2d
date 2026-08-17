use std::collections::BTreeMap;

use crate::{Diagnostic, EncodingSource, RawDocument, TextEncoding};

pub type EntityId = u64;

#[derive(Debug, Clone, PartialEq)]
pub struct Point2 {
    pub x: f64,
    pub y: f64,
}

impl Point2 {
    pub const fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }

    pub fn distance_to(&self, other: &Self) -> f64 {
        (other.x - self.x).hypot(other.y - self.y)
    }

    pub fn angle_to(&self, other: &Self) -> f64 {
        (other.y - self.y)
            .atan2(other.x - self.x)
            .rem_euclid(std::f64::consts::TAU)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Bounds2 {
    pub min: Point2,
    pub max: Point2,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TextValue {
    pub bytes: Vec<u8>,
    pub text: Option<String>,
    pub encoding: Option<TextEncoding>,
}

impl TextValue {
    pub fn from_bytes(bytes: &[u8]) -> Self {
        Self {
            bytes: bytes.to_vec(),
            text: std::str::from_utf8(bytes).ok().map(str::to_owned),
            encoding: std::str::from_utf8(bytes).ok().map(|_| TextEncoding::Utf8),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EncodingInfo {
    pub encoding: Option<TextEncoding>,
    pub source: EncodingSource,
    /// The ASCII label after `ENCODING:` when section #~1 declares one.
    pub declared_name: Option<String>,
}

/// Verified fields from the legacy MI 2.10 global section.
#[derive(Debug, Clone, PartialEq)]
pub struct GlobalInfo {
    pub section_index: usize,
    pub drawing_name: Option<TextValue>,
    pub creation_date: Option<TextValue>,
    pub creation_time: Option<TextValue>,
    pub producer: Option<TextValue>,
    pub version: Option<String>,
    pub dimension: Option<String>,
    pub extents: Option<Bounds2>,
    pub paper_size: Option<String>,
    pub drawing_scale: Option<f64>,
    pub unit: Option<String>,
    pub angle_unit: Option<String>,
    /// The 16 serialized values are retained without assuming row/column order.
    pub transform_values: Option<[f64; 16]>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityHeader {
    pub id: EntityId,
    pub raw_record_index: usize,
    pub part_index: Option<usize>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct GraphicHeader {
    pub entity: EntityHeader,
    /// Compatibility view of the four legacy values: color, linetype, lineweight,
    /// and property count. Modern variable-property headers expose `None`.
    pub display_values: Option<[i64; 4]>,
    pub color: i64,
    pub linetype: i64,
    pub lineweight: f64,
    /// Visibility remains absent until the modern header flag is independently verified.
    pub visibility: Option<bool>,
    /// Extra modern header value retained without assigning visibility semantics.
    pub visibility_value: Option<i64>,
    pub property_ids: Vec<EntityId>,
    /// First property pointer retained for compatibility with the original API.
    pub property_id: Option<EntityId>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PointEntity {
    pub entity: EntityHeader,
    pub location: Point2,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineEntity {
    pub graphic: GraphicHeader,
    pub start_id: EntityId,
    pub end_id: EntityId,
    pub start: Option<Point2>,
    pub end: Option<Point2>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ArcEntity {
    pub entity: EntityHeader,
    /// Present for the verified legacy layout. Modern layouts retain their prefix verbatim.
    pub graphic: Option<GraphicHeader>,
    /// Fields between the entity ID and the terminal center/start/end/orientation fields.
    pub prefix_values: Vec<Vec<u8>>,
    pub center_id: EntityId,
    pub start_id: EntityId,
    pub end_id: EntityId,
    /// Serialized orientation code. Its raw value is retained even when unsupported.
    pub orientation: i64,
    pub center: Option<Point2>,
    pub start: Option<Point2>,
    pub end: Option<Point2>,
}

impl ArcEntity {
    /// Return the verified curve direction without guessing unknown orientation codes.
    pub const fn ccw(&self) -> Option<bool> {
        match self.orientation {
            0 => Some(true),
            _ => None,
        }
    }

    pub fn radius(&self) -> Option<f64> {
        Some(self.center.as_ref()?.distance_to(self.start.as_ref()?))
    }

    pub fn start_angle(&self) -> Option<f64> {
        Some(self.center.as_ref()?.angle_to(self.start.as_ref()?))
    }

    pub fn end_angle(&self) -> Option<f64> {
        Some(self.center.as_ref()?.angle_to(self.end.as_ref()?))
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BSplineSample {
    pub point_id: EntityId,
    pub parameter: f64,
    /// Five serialized values whose formal meanings are not yet verified.
    pub definition_values: [f64; 5],
    pub point: Option<Point2>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BSplineEntity {
    pub entity: EntityHeader,
    /// Present for the verified legacy layout. Modern layouts retain their prefix verbatim.
    pub graphic: Option<GraphicHeader>,
    /// Fields between the entity ID and the verified spline definition.
    pub prefix_values: Vec<Vec<u8>>,
    pub order: usize,
    /// Two serialized values immediately following `order`.
    pub definition_values: [Vec<u8>; 2],
    /// Curve flags are `None` when the selected MI layout does not record verified semantics.
    pub closed: Option<bool>,
    pub periodic: Option<bool>,
    pub rational: Option<bool>,
    /// Rational control-point weights, when explicitly present in a verified layout.
    pub weights: Option<Vec<f64>>,
    pub parameter_max: f64,
    pub start_id: EntityId,
    pub end_id: EntityId,
    pub start: Option<Point2>,
    pub end: Option<Point2>,
    pub control_point_ids: Vec<EntityId>,
    pub control_points: Vec<Option<Point2>>,
    pub knots: Vec<f64>,
    pub samples: Vec<BSplineSample>,
    /// All fields after the entity ID, retained without speculative names.
    pub values: Vec<Vec<u8>>,
}

impl BSplineEntity {
    pub const fn degree(&self) -> usize {
        self.order.saturating_sub(1)
    }

    pub fn parameter_domain(&self) -> Option<(f64, f64)> {
        let degree = self.degree();
        let end_index = self.control_point_ids.len();
        Some((*self.knots.get(degree)?, *self.knots.get(end_index)?))
    }

    /// Evaluate the B-spline with De Boor's algorithm.
    pub fn evaluate(&self, parameter: f64) -> Option<Point2> {
        if !parameter.is_finite() || self.control_points.iter().any(Option::is_none) {
            return None;
        }
        let points = self
            .control_points
            .iter()
            .map(|point| point.as_ref().expect("checked above"))
            .collect::<Vec<_>>();
        let degree = self.degree();
        let last = points.len().checked_sub(1)?;
        let (domain_start, domain_end) = self.parameter_domain()?;
        if parameter < domain_start || parameter > domain_end {
            return None;
        }

        let knot_span = if parameter == domain_end {
            last
        } else {
            (degree..=last).find(|index| {
                self.knots[*index] <= parameter && parameter < self.knots[*index + 1]
            })?
        };
        let weights = if self.rational == Some(true) {
            let weights = self.weights.as_ref()?;
            if weights.len() != points.len() || weights.iter().any(|weight| !weight.is_finite()) {
                return None;
            }
            Some(weights)
        } else {
            None
        };
        let homogeneous = points
            .iter()
            .enumerate()
            .map(|(index, point)| {
                let weight = weights.map_or(1.0, |values| values[index]);
                (point.x * weight, point.y * weight, weight)
            })
            .collect::<Vec<_>>();
        let mut work = (0..=degree)
            .map(|offset| homogeneous[knot_span - degree + offset])
            .collect::<Vec<_>>();
        for level in 1..=degree {
            for offset in (level..=degree).rev() {
                let knot_index = knot_span - degree + offset;
                let denominator =
                    self.knots[knot_index + degree - level + 1] - self.knots[knot_index];
                let alpha = if denominator == 0.0 {
                    0.0
                } else {
                    (parameter - self.knots[knot_index]) / denominator
                };
                work[offset] = (
                    (1.0 - alpha) * work[offset - 1].0 + alpha * work[offset].0,
                    (1.0 - alpha) * work[offset - 1].1 + alpha * work[offset].1,
                    (1.0 - alpha) * work[offset - 1].2 + alpha * work[offset].2,
                );
            }
        }
        let (x, y, weight) = work.pop()?;
        if weight.abs() <= f64::EPSILON {
            return None;
        }
        Some(Point2::new(x / weight, y / weight))
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CircleEntity {
    pub graphic: GraphicHeader,
    pub center_id: EntityId,
    pub circumference_id: EntityId,
    pub center: Option<Point2>,
    pub circumference: Option<Point2>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextEntity {
    pub graphic: GraphicHeader,
    /// Text origin adjustment code: 1 (lower-left) through 9 (upper-right).
    pub alignment: usize,
    /// Serialized row-major 3x3 transform.
    pub transform_values: [f64; 9],
    pub font_name: TextValue,
    pub alternate_font_name: Option<TextValue>,
    /// Serialized character width and height values.
    pub size_values: [f64; 2],
    pub line_spacing: f64,
    pub lines: Vec<TextValue>,
    pub content: TextValue,
    /// All fields after the entity ID, retained without speculative names.
    pub values: Vec<Vec<u8>>,
}

impl TextEntity {
    /// Translation entries verified against the paired legacy DXF corpus.
    pub fn origin(&self) -> Point2 {
        Point2::new(self.transform_values[2], self.transform_values[5])
    }

    pub const fn height(&self) -> f64 {
        self.size_values[1]
    }

    pub fn rotation(&self) -> f64 {
        self.transform_values[3]
            .atan2(self.transform_values[0])
            .rem_euclid(std::f64::consts::TAU)
    }

    pub fn width_factor(&self) -> Option<f64> {
        (self.size_values[1] != 0.0).then_some(self.size_values[0] / self.size_values[1])
    }

    pub fn is_mirrored(&self) -> bool {
        self.transform_values[0] * self.transform_values[4]
            - self.transform_values[3] * self.transform_values[1]
            < 0.0
    }
}

impl CircleEntity {
    pub fn radius(&self) -> Option<f64> {
        Some(
            self.center
                .as_ref()?
                .distance_to(self.circumference.as_ref()?),
        )
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PropertyEntity {
    pub entity: EntityHeader,
    pub mi_type: String,
    pub values: Vec<Vec<u8>>,
    pub part_status: Option<PartStatusProperty>,
    pub associated_strings: Option<Vec<TextValue>>,
    pub dimension_text_attribute: Option<DimensionTextAttributeProperty>,
    pub integer_definition: Option<Vec<i64>>,
    pub numeric_definition: Option<Vec<f64>>,
    pub hatch_pattern: Option<HatchPatternProperty>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PartStatusProperty {
    pub shared: bool,
    pub scale_modifiable: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DimensionTextAttributeProperty {
    pub font_name: TextValue,
    pub alternate_font_name: TextValue,
    pub symbol_font_name: TextValue,
    /// Remaining serialized numeric values. Their individual meanings vary by MI version.
    pub definition_values: Vec<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HatchPatternLine {
    pub offset: f64,
    pub distance: f64,
    pub angle: f64,
    pub color: i64,
    pub linetype: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HatchPatternProperty {
    pub lines: Vec<HatchPatternLine>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DimensionEntity {
    pub entity: EntityHeader,
    pub mi_type: String,
    pub property_ids: Vec<EntityId>,
    pub reference_geometry_ids: Vec<EntityId>,
    pub reference_point_ids: Vec<EntityId>,
    pub text_position: Point2,
    pub measurement: f64,
    pub formatted_text: TextValue,
    pub dimension_style_id: Option<EntityId>,
    pub text_style_id: Option<EntityId>,
    pub tolerance_ids: Vec<EntityId>,
    /// All fields after the entity ID, retained for version-specific inspection.
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DimensionToleranceEntity {
    pub entity: EntityHeader,
    /// Serialized DTV definition code retained until its enumeration is verified.
    pub definition_value: i64,
    pub upper_value: f64,
    pub lower_value: f64,
    /// Serialized formatting code retained until its enumeration is verified.
    pub format_value: i64,
    pub upper_text: TextValue,
    pub lower_text: TextValue,
    pub text_style_id: EntityId,
    /// Text origin adjustment code: 1 (lower-left) through 9 (upper-right).
    pub alignment: usize,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LeaderPoint {
    pub location: Point2,
    pub elevation: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LeaderEntity {
    pub graphic: GraphicHeader,
    /// Serialized terminator code retained until its enumeration is verified.
    pub arrow_type: i64,
    pub arrow_size: f64,
    pub points: Vec<LeaderPoint>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ContourEntity {
    pub graphic: GraphicHeader,
    pub closed: bool,
    /// Serialized contour direction code retained without guessing clockwise/counter-clockwise.
    pub orientation: i64,
    pub component_ids: Vec<EntityId>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HatchEntity {
    pub graphic: GraphicHeader,
    pub reference_point: Point2,
    pub angle: f64,
    pub spacing: f64,
    /// Ordered outer loop followed by zero or more inner loops, populated from PFA.
    pub boundary_loop_ids: Vec<EntityId>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HatchAssociationEntity {
    pub entity: EntityHeader,
    pub property_ids: Vec<EntityId>,
    pub hatch_id: EntityId,
    pub outer_loop_id: EntityId,
    pub inner_loop_ids: Vec<EntityId>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SymbolEntity {
    pub entity: EntityHeader,
    pub component_ids: Vec<EntityId>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructuredEntity {
    pub entity: EntityHeader,
    pub mi_type: String,
    /// All fields after the entity ID, retained without speculative names.
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AssemblyInstance {
    /// A separator value present before every instance after the first.
    pub relation_value: Option<Vec<u8>>,
    /// Three serialized relationship values whose formal meanings are not yet verified.
    pub definition_values: [Vec<u8>; 3],
    pub member_ids: Vec<EntityId>,
    pub assembly_id: EntityId,
    /// Serialized 3x3 transform values retained without assuming matrix convention.
    pub transform_values: [f64; 9],
    pub target_part_index: Option<usize>,
    pub is_sheet: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AssemblyEntity {
    pub entity: EntityHeader,
    pub property_ids: Vec<EntityId>,
    pub part_name: Option<TextValue>,
    pub instances: Vec<AssemblyInstance>,
    pub definition_part_index: Option<usize>,
    pub values: Vec<Vec<u8>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnsupportedEntity {
    pub entity: EntityHeader,
    pub mi_type: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SemanticEntity {
    Point(PointEntity),
    Line(LineEntity),
    Arc(ArcEntity),
    Fillet(ArcEntity),
    BSpline(BSplineEntity),
    Circle(CircleEntity),
    Text(TextEntity),
    Dimension(DimensionEntity),
    DimensionTolerance(DimensionToleranceEntity),
    Leader(LeaderEntity),
    Contour(ContourEntity),
    Hatch(HatchEntity),
    HatchAssociation(HatchAssociationEntity),
    Symbol(SymbolEntity),
    Property(PropertyEntity),
    Assembly(AssemblyEntity),
    Unsupported(UnsupportedEntity),
}

impl SemanticEntity {
    pub const fn header(&self) -> &EntityHeader {
        match self {
            Self::Point(value) => &value.entity,
            Self::Line(value) => &value.graphic.entity,
            Self::Arc(value) => &value.entity,
            Self::Fillet(value) => &value.entity,
            Self::BSpline(value) => &value.entity,
            Self::Circle(value) => &value.graphic.entity,
            Self::Text(value) => &value.graphic.entity,
            Self::Dimension(value) => &value.entity,
            Self::DimensionTolerance(value) => &value.entity,
            Self::Leader(value) => &value.graphic.entity,
            Self::Contour(value) => &value.graphic.entity,
            Self::Hatch(value) => &value.graphic.entity,
            Self::HatchAssociation(value) => &value.entity,
            Self::Symbol(value) => &value.entity,
            Self::Property(value) => &value.entity,
            Self::Assembly(value) => &value.entity,
            Self::Unsupported(value) => &value.entity,
        }
    }

    pub const fn id(&self) -> EntityId {
        self.header().id
    }

    pub const fn raw_record_index(&self) -> usize {
        self.header().raw_record_index
    }

    pub const fn part_index(&self) -> Option<usize> {
        self.header().part_index
    }

    pub fn mi_type(&self) -> &str {
        match self {
            Self::Point(_) => "P",
            Self::Line(_) => "LIN",
            Self::Arc(_) => "ARC",
            Self::Fillet(_) => "FIL",
            Self::BSpline(_) => "BSPL",
            Self::Circle(_) => "CIR",
            Self::Text(_) => "TEX",
            Self::Dimension(value) => &value.mi_type,
            Self::DimensionTolerance(_) => "DTV",
            Self::Leader(_) => "LED",
            Self::Contour(_) => "COC",
            Self::Hatch(_) => "HAT",
            Self::HatchAssociation(_) => "PFA",
            Self::Symbol(_) => "SYML",
            Self::Property(value) => &value.mi_type,
            Self::Assembly(_) => "ASSE",
            Self::Unsupported(value) => &value.mi_type,
        }
    }

    pub const fn is_graphic(&self) -> bool {
        matches!(
            self,
            Self::Line(_)
                | Self::Arc(_)
                | Self::Fillet(_)
                | Self::BSpline(_)
                | Self::Circle(_)
                | Self::Text(_)
        )
    }

    pub const fn is_annotation(&self) -> bool {
        matches!(
            self,
            Self::Dimension(_)
                | Self::DimensionTolerance(_)
                | Self::Leader(_)
                | Self::Hatch(_)
                | Self::Symbol(_)
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Part {
    pub index: usize,
    pub name: TextValue,
    pub definition_section_index: usize,
    pub point_ids: Vec<EntityId>,
    pub graphic_entity_ids: Vec<EntityId>,
    pub annotation_entity_ids: Vec<EntityId>,
    pub unsupported_entity_ids: Vec<EntityId>,
    pub source_entity_ids: Vec<EntityId>,
    pub assembly_id: Option<EntityId>,
    /// Child indexes preserve instance order and may contain duplicates for shared parts.
    pub child_part_indices: Vec<usize>,
    pub parent_part_indices: Vec<usize>,
}

/// Native semantic document with the complete Phase 1 raw scan retained.
#[derive(Debug, Clone, PartialEq)]
pub struct SemanticDocument {
    pub raw: RawDocument,
    pub encoding: EncodingInfo,
    pub global: Option<GlobalInfo>,
    pub toc_last_entity: Option<EntityId>,
    pub parts: Vec<Part>,
    pub top_part_index: Option<usize>,
    pub root_part_indices: Vec<usize>,
    pub sheet_part_indices: Vec<usize>,
    pub entities: Vec<SemanticEntity>,
    /// Maps an ID to the first source occurrence; duplicates remain in `entities`.
    pub entity_index: BTreeMap<EntityId, usize>,
    pub diagnostics: Vec<Diagnostic>,
}

impl SemanticDocument {
    pub fn entity(&self, id: EntityId) -> Option<&SemanticEntity> {
        self.entity_index
            .get(&id)
            .and_then(|index| self.entities.get(*index))
    }
}
