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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphicHeader {
    pub entity: EntityHeader,
    /// Four legacy display fields whose formal names are not yet verified.
    pub display_values: [i64; 4],
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
    pub graphic: GraphicHeader,
    pub center_id: EntityId,
    pub start_id: EntityId,
    pub end_id: EntityId,
    /// Legacy orientation field. Its value is retained even when unsupported.
    pub orientation: i64,
    pub center: Option<Point2>,
    pub start: Option<Point2>,
    pub end: Option<Point2>,
}

impl ArcEntity {
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

    /// Evaluate the non-rational B-spline with De Boor's algorithm.
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
        let mut work = (0..=degree)
            .map(|offset| points[knot_span - degree + offset].clone())
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
                work[offset] = Point2::new(
                    (1.0 - alpha) * work[offset - 1].x + alpha * work[offset].x,
                    (1.0 - alpha) * work[offset - 1].y + alpha * work[offset].y,
                );
            }
        }
        work.pop()
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
    /// Nine serialized transform values from fields 8 through 16.
    pub transform_values: [f64; 9],
    pub font_name: TextValue,
    /// Two serialized text-size values from fields 22 and 23.
    pub size_values: [f64; 2],
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
        self.size_values[0]
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PropertyEntity {
    pub entity: EntityHeader,
    pub mi_type: String,
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
    Dimension(StructuredEntity),
    DimensionTolerance(StructuredEntity),
    Leader(StructuredEntity),
    Hatch(StructuredEntity),
    Symbol(StructuredEntity),
    Property(PropertyEntity),
    Assembly(AssemblyEntity),
    Unsupported(UnsupportedEntity),
}

impl SemanticEntity {
    pub const fn header(&self) -> &EntityHeader {
        match self {
            Self::Point(value) => &value.entity,
            Self::Line(value) => &value.graphic.entity,
            Self::Arc(value) => &value.graphic.entity,
            Self::Fillet(value) => &value.graphic.entity,
            Self::BSpline(value) => &value.entity,
            Self::Circle(value) => &value.graphic.entity,
            Self::Text(value) => &value.graphic.entity,
            Self::Dimension(value)
            | Self::DimensionTolerance(value)
            | Self::Leader(value)
            | Self::Hatch(value)
            | Self::Symbol(value) => &value.entity,
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
            Self::Dimension(value)
            | Self::DimensionTolerance(value)
            | Self::Leader(value)
            | Self::Hatch(value)
            | Self::Symbol(value) => &value.mi_type,
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
