//! PyO3 bindings for `ezmi2d-core`.

use ezmi2d_core::{
    detect_format, read_input_with_encoding, scan_input, ArcEntity, AssemblyInstance,
    BSplineEntity, Bounds2, CircleEntity, ContourEntity, Diagnostic, DimensionEntity,
    DimensionToleranceEntity, EncodingInfo, GlobalInfo, GraphicHeader, HatchAssociationEntity,
    HatchEntity, LeaderEntity, LineEnding, LineEntity, MiError as CoreMiError, MiFormatInfo, Part,
    Point2, RawDocument, RawLineKind, RawRecord, RawSection, ScanOptions, SemanticDocument,
    SemanticEntity, SourceSpan, SymbolEntity, TextEntity, TextValue,
};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule};

create_exception!(
    _core,
    MiError,
    PyException,
    "Base exception raised by ezmi2d."
);
create_exception!(
    _core,
    InvalidMiError,
    MiError,
    "The input is not a structurally recognizable text MI stream."
);
create_exception!(
    _core,
    UnsupportedMiError,
    MiError,
    "The input family was recognized but is not supported by this reader."
);
create_exception!(
    _core,
    MiLimitError,
    MiError,
    "A configured parser resource limit was exceeded."
);

#[pyfunction]
fn core_version() -> String {
    ezmi2d_core::version().to_owned()
}

#[pyfunction]
fn detect_format_bytes(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyDict>> {
    let format = detect_format(data).map_err(core_error_to_python)?;
    Ok(format_dict(py, format)?.unbind())
}

#[pyfunction]
fn scan_mi_records(py: Python<'_>, data: &[u8], limits: Vec<usize>) -> PyResult<Py<PyDict>> {
    let input = scan_input(data, scan_options(&limits)?).map_err(core_error_to_python)?;
    Ok(document_dict(py, &input.document, input.source.as_ref())?.unbind())
}

#[pyfunction]
#[pyo3(signature = (data, limits, encoding=None))]
fn read_legacy_document(
    py: Python<'_>,
    data: &[u8],
    limits: Vec<usize>,
    encoding: Option<&str>,
) -> PyResult<Py<PyDict>> {
    let input = read_input_with_encoding(data, scan_options(&limits)?, encoding)
        .map_err(core_error_to_python)?;
    Ok(semantic_document_dict(py, &input.document, input.source.as_ref())?.unbind())
}

fn scan_options(limits: &[usize]) -> PyResult<ScanOptions> {
    let [max_file_size, max_lines, max_sections, max_records, max_line_size, max_record_size, max_decompressed_size, max_compression_ratio] =
        limits
    else {
        return Err(PyValueError::new_err(format!(
            "expected 8 scan limits, got {}",
            limits.len()
        )));
    };
    Ok(ScanOptions {
        max_file_size: *max_file_size,
        max_lines: *max_lines,
        max_sections: *max_sections,
        max_records: *max_records,
        max_line_size: *max_line_size,
        max_record_size: *max_record_size,
        max_decompressed_size: *max_decompressed_size,
        max_compression_ratio: *max_compression_ratio,
    })
}

fn document_dict<'py>(
    py: Python<'py>,
    document: &RawDocument,
    logical_source: &[u8],
) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("format", format_dict(py, document.format)?)?;
    result.set_item("container_size", document.container_size)?;
    result.set_item("source_size", document.source_size)?;
    if document.format.compression.is_some() {
        result.set_item("logical_source", PyBytes::new(py, logical_source))?;
    } else {
        result.set_item("logical_source", py.None())?;
    }
    result.set_item("termination", document.termination.as_str())?;
    result.set_item("end_offset", document.end_offset)?;
    result.set_item("trailing_bytes", document.trailing_bytes)?;
    result.set_item("preamble", span_dict(py, document.preamble_span)?)?;
    if let Some(span) = document.file_terminator_span {
        result.set_item("file_terminator", span_dict(py, span)?)?;
    } else {
        result.set_item("file_terminator", py.None())?;
    }

    let newline = PyDict::new(py);
    newline.set_item("lf", document.newlines.lf)?;
    newline.set_item("crlf", document.newlines.crlf)?;
    newline.set_item("cr", document.newlines.cr)?;
    newline.set_item("unterminated", document.newlines.unterminated)?;
    result.set_item("newlines", newline)?;

    result.set_item("lines_packed", packed_lines(py, document))?;

    let records = PyList::empty(py);
    for record in &document.records {
        records.append(record_dict(py, record)?)?;
    }
    result.set_item("records", records)?;

    let sections = PyList::empty(py);
    for section in &document.sections {
        sections.append(section_dict(py, section)?)?;
    }
    result.set_item("sections", sections)?;

    let diagnostics = PyList::empty(py);
    for diagnostic in &document.diagnostics {
        diagnostics.append(diagnostic_dict(py, diagnostic)?)?;
    }
    result.set_item("diagnostics", diagnostics)?;
    Ok(result)
}

fn semantic_document_dict<'py>(
    py: Python<'py>,
    document: &SemanticDocument,
    logical_source: &[u8],
) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("raw", document_dict(py, &document.raw, logical_source)?)?;
    result.set_item("encoding", encoding_dict(py, &document.encoding)?)?;
    if let Some(global) = &document.global {
        result.set_item("global", global_dict(py, global)?)?;
    } else {
        result.set_item("global", py.None())?;
    }
    result.set_item("toc_last_entity", document.toc_last_entity)?;
    result.set_item("top_part_index", document.top_part_index)?;
    result.set_item("root_part_indices", &document.root_part_indices)?;
    result.set_item("sheet_part_indices", &document.sheet_part_indices)?;

    let parts = PyList::empty(py);
    for part in &document.parts {
        parts.append(part_dict(py, part)?)?;
    }
    result.set_item("parts", parts)?;

    let entities = PyList::empty(py);
    for entity in &document.entities {
        entities.append(entity_dict(py, entity)?)?;
    }
    result.set_item("entities", entities)?;

    let diagnostics = PyList::empty(py);
    for diagnostic in &document.diagnostics {
        diagnostics.append(diagnostic_dict(py, diagnostic)?)?;
    }
    result.set_item("diagnostics", diagnostics)?;
    Ok(result)
}

fn encoding_dict<'py>(py: Python<'py>, info: &EncodingInfo) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("name", info.encoding.map(|encoding| encoding.name()))?;
    result.set_item("source", info.source.as_str())?;
    result.set_item("declared_name", info.declared_name.as_deref())?;
    Ok(result)
}

fn global_dict<'py>(py: Python<'py>, global: &GlobalInfo) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("section_index", global.section_index)?;
    set_optional_text(py, &result, "drawing_name", global.drawing_name.as_ref())?;
    set_optional_text(py, &result, "creation_date", global.creation_date.as_ref())?;
    set_optional_text(py, &result, "creation_time", global.creation_time.as_ref())?;
    set_optional_text(py, &result, "producer", global.producer.as_ref())?;
    result.set_item("version", global.version.as_deref())?;
    result.set_item("dimension", global.dimension.as_deref())?;
    if let Some(extents) = &global.extents {
        result.set_item("extents", bounds_dict(py, extents)?)?;
    } else {
        result.set_item("extents", py.None())?;
    }
    result.set_item("paper_size", global.paper_size.as_deref())?;
    result.set_item("drawing_scale", global.drawing_scale)?;
    result.set_item("unit", global.unit.as_deref())?;
    result.set_item("angle_unit", global.angle_unit.as_deref())?;
    result.set_item(
        "transform_values",
        global.transform_values.map(|values| values.to_vec()),
    )?;
    Ok(result)
}

fn set_optional_text(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    name: &str,
    value: Option<&TextValue>,
) -> PyResult<()> {
    if let Some(value) = value {
        result.set_item(name, text_dict(py, value)?)?;
    } else {
        result.set_item(name, py.None())?;
    }
    Ok(())
}

fn text_dict<'py>(py: Python<'py>, value: &TextValue) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("bytes", PyBytes::new(py, &value.bytes))?;
    result.set_item("text", value.text.as_deref())?;
    result.set_item("encoding", value.encoding.map(|encoding| encoding.name()))?;
    Ok(result)
}

fn point_dict<'py>(py: Python<'py>, point: &Point2) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("x", point.x)?;
    result.set_item("y", point.y)?;
    Ok(result)
}

fn optional_point_dict<'py>(
    py: Python<'py>,
    point: Option<&Point2>,
) -> PyResult<Bound<'py, PyAny>> {
    if let Some(point) = point {
        Ok(point_dict(py, point)?.into_any())
    } else {
        Ok(py.None().into_bound(py))
    }
}

fn bounds_dict<'py>(py: Python<'py>, bounds: &Bounds2) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("min", point_dict(py, &bounds.min)?)?;
    result.set_item("max", point_dict(py, &bounds.max)?)?;
    Ok(result)
}

fn part_dict<'py>(py: Python<'py>, part: &Part) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("index", part.index)?;
    result.set_item("name", text_dict(py, &part.name)?)?;
    result.set_item("definition_section_index", part.definition_section_index)?;
    result.set_item("point_ids", &part.point_ids)?;
    result.set_item("graphic_entity_ids", &part.graphic_entity_ids)?;
    result.set_item("annotation_entity_ids", &part.annotation_entity_ids)?;
    result.set_item("unsupported_entity_ids", &part.unsupported_entity_ids)?;
    result.set_item("source_entity_ids", &part.source_entity_ids)?;
    result.set_item("assembly_id", part.assembly_id)?;
    result.set_item("child_part_indices", &part.child_part_indices)?;
    result.set_item("parent_part_indices", &part.parent_part_indices)?;
    Ok(result)
}

fn entity_dict<'py>(py: Python<'py>, entity: &SemanticEntity) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("id", entity.id())?;
    result.set_item("mi_type", entity.mi_type())?;
    result.set_item("raw_record_index", entity.raw_record_index())?;
    result.set_item("part_index", entity.part_index())?;

    match entity {
        SemanticEntity::Point(point) => {
            result.set_item("kind", "point")?;
            result.set_item("location", point_dict(py, &point.location)?)?;
        }
        SemanticEntity::Line(line) => {
            result.set_item("kind", "line")?;
            set_graphic_fields(&result, &line.graphic)?;
            set_line_fields(py, &result, line)?;
        }
        SemanticEntity::Arc(arc) => {
            result.set_item("kind", "arc")?;
            set_optional_graphic_fields(py, &result, arc.graphic.as_ref())?;
            set_arc_fields(py, &result, arc)?;
        }
        SemanticEntity::Fillet(fillet) => {
            result.set_item("kind", "fillet")?;
            set_optional_graphic_fields(py, &result, fillet.graphic.as_ref())?;
            set_arc_fields(py, &result, fillet)?;
        }
        SemanticEntity::BSpline(spline) => {
            result.set_item("kind", "bspline")?;
            set_bspline_fields(py, &result, spline)?;
        }
        SemanticEntity::Circle(circle) => {
            result.set_item("kind", "circle")?;
            set_graphic_fields(&result, &circle.graphic)?;
            set_circle_fields(py, &result, circle)?;
        }
        SemanticEntity::Text(text) => {
            result.set_item("kind", "text")?;
            set_graphic_fields(&result, &text.graphic)?;
            set_text_fields(py, &result, text)?;
        }
        SemanticEntity::Dimension(value) => {
            result.set_item("kind", "dimension")?;
            set_dimension_fields(py, &result, value)?;
        }
        SemanticEntity::DimensionTolerance(value) => {
            result.set_item("kind", "dimension_tolerance")?;
            set_dimension_tolerance_fields(py, &result, value)?;
        }
        SemanticEntity::Leader(value) => {
            result.set_item("kind", "leader")?;
            set_graphic_fields(&result, &value.graphic)?;
            set_leader_fields(py, &result, value)?;
        }
        SemanticEntity::Contour(value) => {
            result.set_item("kind", "contour")?;
            set_graphic_fields(&result, &value.graphic)?;
            set_contour_fields(py, &result, value)?;
        }
        SemanticEntity::Hatch(value) => {
            result.set_item("kind", "hatch")?;
            set_graphic_fields(&result, &value.graphic)?;
            set_hatch_fields(py, &result, value)?;
        }
        SemanticEntity::HatchAssociation(value) => {
            result.set_item("kind", "hatch_association")?;
            set_hatch_association_fields(py, &result, value)?;
        }
        SemanticEntity::Symbol(value) => {
            result.set_item("kind", "symbol")?;
            set_symbol_fields(py, &result, value)?;
        }
        SemanticEntity::Property(property) => {
            result.set_item("kind", "property")?;
            let values = PyList::empty(py);
            for value in &property.values {
                values.append(PyBytes::new(py, value))?;
            }
            result.set_item("values", values)?;
            if let Some(status) = &property.part_status {
                let status_value = PyDict::new(py);
                status_value.set_item("shared", status.shared)?;
                status_value.set_item("scale_modifiable", status.scale_modifiable)?;
                result.set_item("part_status", status_value)?;
            } else {
                result.set_item("part_status", py.None())?;
            }
            if let Some(strings) = &property.associated_strings {
                let string_values = PyList::empty(py);
                for value in strings {
                    string_values.append(text_dict(py, value)?)?;
                }
                result.set_item("associated_strings", string_values)?;
            } else {
                result.set_item("associated_strings", py.None())?;
            }
            if let Some(attribute) = &property.dimension_text_attribute {
                let value = PyDict::new(py);
                value.set_item("font_name", text_dict(py, &attribute.font_name)?)?;
                value.set_item(
                    "alternate_font_name",
                    text_dict(py, &attribute.alternate_font_name)?,
                )?;
                value.set_item(
                    "symbol_font_name",
                    text_dict(py, &attribute.symbol_font_name)?,
                )?;
                value.set_item("definition_values", &attribute.definition_values)?;
                result.set_item("dimension_text_attribute", value)?;
            } else {
                result.set_item("dimension_text_attribute", py.None())?;
            }
            result.set_item("integer_definition", property.integer_definition.as_deref())?;
            result.set_item("numeric_definition", property.numeric_definition.as_deref())?;
            if let Some(pattern) = &property.hatch_pattern {
                let lines = PyList::empty(py);
                for line in &pattern.lines {
                    let value = PyDict::new(py);
                    value.set_item("offset", line.offset)?;
                    value.set_item("distance", line.distance)?;
                    value.set_item("angle", line.angle)?;
                    value.set_item("color", line.color)?;
                    value.set_item("linetype", line.linetype)?;
                    lines.append(value)?;
                }
                result.set_item("hatch_pattern", lines)?;
            } else {
                result.set_item("hatch_pattern", py.None())?;
            }
        }
        SemanticEntity::Assembly(assembly) => {
            result.set_item("kind", "assembly")?;
            result.set_item("property_ids", &assembly.property_ids)?;
            set_optional_text(py, &result, "part_name", assembly.part_name.as_ref())?;
            let instances = PyList::empty(py);
            for instance in &assembly.instances {
                instances.append(assembly_instance_dict(py, instance)?)?;
            }
            result.set_item("instances", instances)?;
            result.set_item("definition_part_index", assembly.definition_part_index)?;
            result.set_item("values", byte_values(py, &assembly.values)?)?;
        }
        SemanticEntity::Unsupported(_) => {
            result.set_item("kind", "unsupported")?;
        }
    }
    Ok(result)
}

fn set_dimension_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &DimensionEntity,
) -> PyResult<()> {
    result.set_item("property_ids", &value.property_ids)?;
    result.set_item("reference_geometry_ids", &value.reference_geometry_ids)?;
    result.set_item("reference_point_ids", &value.reference_point_ids)?;
    result.set_item("text_position", point_dict(py, &value.text_position)?)?;
    result.set_item("measurement", value.measurement)?;
    result.set_item("formatted_text", text_dict(py, &value.formatted_text)?)?;
    result.set_item("dimension_style_id", value.dimension_style_id)?;
    result.set_item("text_style_id", value.text_style_id)?;
    result.set_item("tolerance_ids", &value.tolerance_ids)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_dimension_tolerance_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &DimensionToleranceEntity,
) -> PyResult<()> {
    result.set_item("definition_value", value.definition_value)?;
    result.set_item("upper_value", value.upper_value)?;
    result.set_item("lower_value", value.lower_value)?;
    result.set_item("format_value", value.format_value)?;
    result.set_item("upper_text", text_dict(py, &value.upper_text)?)?;
    result.set_item("lower_text", text_dict(py, &value.lower_text)?)?;
    result.set_item("text_style_id", value.text_style_id)?;
    result.set_item("alignment", value.alignment)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_leader_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &LeaderEntity,
) -> PyResult<()> {
    result.set_item("arrow_type", value.arrow_type)?;
    result.set_item("arrow_size", value.arrow_size)?;
    let points = PyList::empty(py);
    for point in &value.points {
        let row = point_dict(py, &point.location)?;
        row.set_item("z", point.elevation)?;
        points.append(row)?;
    }
    result.set_item("points", points)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_contour_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &ContourEntity,
) -> PyResult<()> {
    result.set_item("closed", value.closed)?;
    result.set_item("orientation", value.orientation)?;
    result.set_item("component_ids", &value.component_ids)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_hatch_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &HatchEntity,
) -> PyResult<()> {
    result.set_item("reference_point", point_dict(py, &value.reference_point)?)?;
    result.set_item("angle", value.angle)?;
    result.set_item("spacing", value.spacing)?;
    result.set_item("boundary_loop_ids", &value.boundary_loop_ids)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_hatch_association_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &HatchAssociationEntity,
) -> PyResult<()> {
    result.set_item("property_ids", &value.property_ids)?;
    result.set_item("hatch_id", value.hatch_id)?;
    result.set_item("outer_loop_id", value.outer_loop_id)?;
    result.set_item("inner_loop_ids", &value.inner_loop_ids)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn set_symbol_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    value: &SymbolEntity,
) -> PyResult<()> {
    result.set_item("component_ids", &value.component_ids)?;
    result.set_item("values", byte_values(py, &value.values)?)?;
    Ok(())
}

fn byte_values<'py>(py: Python<'py>, values: &[Vec<u8>]) -> PyResult<Bound<'py, PyList>> {
    let result = PyList::empty(py);
    for value in values {
        result.append(PyBytes::new(py, value))?;
    }
    Ok(result)
}

fn assembly_instance_dict<'py>(
    py: Python<'py>,
    instance: &AssemblyInstance,
) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item(
        "relation_value",
        instance
            .relation_value
            .as_ref()
            .map(|value| PyBytes::new(py, value)),
    )?;
    result.set_item(
        "definition_values",
        byte_values(py, &instance.definition_values)?,
    )?;
    result.set_item("member_ids", &instance.member_ids)?;
    result.set_item("assembly_id", instance.assembly_id)?;
    result.set_item("transform_values", instance.transform_values.to_vec())?;
    result.set_item("target_part_index", instance.target_part_index)?;
    result.set_item("is_sheet", instance.is_sheet)?;
    Ok(result)
}

fn set_bspline_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    spline: &BSplineEntity,
) -> PyResult<()> {
    set_optional_graphic_fields(py, result, spline.graphic.as_ref())?;
    result.set_item("prefix_values", byte_values(py, &spline.prefix_values)?)?;
    result.set_item("order", spline.order)?;
    result.set_item("degree", spline.degree())?;
    result.set_item(
        "definition_values",
        byte_values(py, &spline.definition_values)?,
    )?;
    result.set_item("closed", spline.closed)?;
    result.set_item("periodic", spline.periodic)?;
    result.set_item("rational", spline.rational)?;
    result.set_item("weights", spline.weights.as_deref())?;
    result.set_item("parameter_max", spline.parameter_max)?;
    result.set_item("parameter_domain", spline.parameter_domain())?;
    result.set_item("start_id", spline.start_id)?;
    result.set_item("end_id", spline.end_id)?;
    result.set_item("start", optional_point_dict(py, spline.start.as_ref())?)?;
    result.set_item("end", optional_point_dict(py, spline.end.as_ref())?)?;
    result.set_item("control_point_ids", &spline.control_point_ids)?;
    let control_points = PyList::empty(py);
    for point in &spline.control_points {
        control_points.append(optional_point_dict(py, point.as_ref())?)?;
    }
    result.set_item("control_points", control_points)?;
    result.set_item("knots", &spline.knots)?;
    let samples = PyList::empty(py);
    for sample in &spline.samples {
        let value = PyDict::new(py);
        value.set_item("point_id", sample.point_id)?;
        value.set_item("parameter", sample.parameter)?;
        value.set_item("definition_values", sample.definition_values.to_vec())?;
        value.set_item("point", optional_point_dict(py, sample.point.as_ref())?)?;
        samples.append(value)?;
    }
    result.set_item("samples", samples)?;
    result.set_item("values", byte_values(py, &spline.values)?)?;
    Ok(())
}

fn set_text_fields(py: Python<'_>, result: &Bound<'_, PyDict>, text: &TextEntity) -> PyResult<()> {
    result.set_item("alignment", text.alignment)?;
    result.set_item("transform_values", text.transform_values.to_vec())?;
    result.set_item("origin", point_dict(py, &text.origin())?)?;
    result.set_item("rotation", text.rotation())?;
    result.set_item("width_factor", text.width_factor())?;
    result.set_item("mirrored", text.is_mirrored())?;
    result.set_item("font_name", text_dict(py, &text.font_name)?)?;
    set_optional_text(
        py,
        result,
        "alternate_font_name",
        text.alternate_font_name.as_ref(),
    )?;
    result.set_item("size_values", text.size_values.to_vec())?;
    result.set_item("height", text.height())?;
    result.set_item("line_spacing", text.line_spacing)?;
    let lines = PyList::empty(py);
    for line in &text.lines {
        lines.append(text_dict(py, line)?)?;
    }
    result.set_item("lines", lines)?;
    result.set_item("content", text_dict(py, &text.content)?)?;
    let values = PyList::empty(py);
    for value in &text.values {
        values.append(PyBytes::new(py, value))?;
    }
    result.set_item("values", values)?;
    Ok(())
}

fn set_graphic_fields(result: &Bound<'_, PyDict>, graphic: &GraphicHeader) -> PyResult<()> {
    result.set_item(
        "display_values",
        graphic.display_values.map(|values| values.to_vec()),
    )?;
    result.set_item("color", graphic.color)?;
    result.set_item("linetype", graphic.linetype)?;
    result.set_item("lineweight", graphic.lineweight)?;
    result.set_item("visibility", graphic.visibility)?;
    result.set_item("visibility_value", graphic.visibility_value)?;
    result.set_item("property_ids", &graphic.property_ids)?;
    result.set_item("property_id", graphic.property_id)?;
    Ok(())
}

fn set_optional_graphic_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    graphic: Option<&GraphicHeader>,
) -> PyResult<()> {
    if let Some(graphic) = graphic {
        set_graphic_fields(result, graphic)
    } else {
        result.set_item("display_values", py.None())?;
        result.set_item("color", py.None())?;
        result.set_item("linetype", py.None())?;
        result.set_item("lineweight", py.None())?;
        result.set_item("visibility", py.None())?;
        result.set_item("visibility_value", py.None())?;
        result.set_item("property_ids", Vec::<u64>::new())?;
        result.set_item("property_id", py.None())?;
        Ok(())
    }
}

fn set_line_fields(py: Python<'_>, result: &Bound<'_, PyDict>, line: &LineEntity) -> PyResult<()> {
    result.set_item("start_id", line.start_id)?;
    result.set_item("end_id", line.end_id)?;
    result.set_item("start", optional_point_dict(py, line.start.as_ref())?)?;
    result.set_item("end", optional_point_dict(py, line.end.as_ref())?)?;
    Ok(())
}

fn set_arc_fields(py: Python<'_>, result: &Bound<'_, PyDict>, arc: &ArcEntity) -> PyResult<()> {
    result.set_item("prefix_values", byte_values(py, &arc.prefix_values)?)?;
    result.set_item("center_id", arc.center_id)?;
    result.set_item("start_id", arc.start_id)?;
    result.set_item("end_id", arc.end_id)?;
    result.set_item("orientation", arc.orientation)?;
    result.set_item("ccw", arc.ccw())?;
    result.set_item("center", optional_point_dict(py, arc.center.as_ref())?)?;
    result.set_item("start", optional_point_dict(py, arc.start.as_ref())?)?;
    result.set_item("end", optional_point_dict(py, arc.end.as_ref())?)?;
    result.set_item("radius", arc.radius())?;
    result.set_item("start_angle", arc.start_angle())?;
    result.set_item("end_angle", arc.end_angle())?;
    Ok(())
}

fn set_circle_fields(
    py: Python<'_>,
    result: &Bound<'_, PyDict>,
    circle: &CircleEntity,
) -> PyResult<()> {
    result.set_item("center_id", circle.center_id)?;
    result.set_item("circumference_id", circle.circumference_id)?;
    result.set_item("center", optional_point_dict(py, circle.center.as_ref())?)?;
    result.set_item(
        "circumference",
        optional_point_dict(py, circle.circumference.as_ref())?,
    )?;
    result.set_item("radius", circle.radius())?;
    Ok(())
}

fn format_dict(py: Python<'_>, format: MiFormatInfo) -> PyResult<Bound<'_, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("kind", format.kind.as_str())?;
    result.set_item(
        "compression",
        format.compression.map(|compression| compression.as_str()),
    )?;
    result.set_item("first_section", format.first_section)?;
    result.set_item("utf8_bom", format.utf8_bom)?;
    Ok(result)
}

/// 行テーブルは1行28バイトの固定長リトルエンディアン列にパックして返す。
/// (number, span_offset, span_length, content_offset, content_length: u32×5、
///  ending: u8、kind: u8、予約: u16、section_number: u32(なし=u32::MAX))
/// 行ごとのPyDict実体化は、70万行規模の圧縮MI(展開4MB超)で1GB超のRSSを
/// 生んでいた。Python側はSequenceとして遅延復元する。
fn packed_lines<'py>(py: Python<'py>, document: &RawDocument) -> Bound<'py, PyBytes> {
    const STRIDE: usize = 28;
    let mut buffer = Vec::with_capacity(document.lines.len() * STRIDE);
    let clamp = |value: usize| u32::try_from(value).unwrap_or(u32::MAX);
    for line in &document.lines {
        buffer.extend_from_slice(&clamp(line.number).to_le_bytes());
        buffer.extend_from_slice(&clamp(line.span.offset).to_le_bytes());
        buffer.extend_from_slice(&clamp(line.span.length).to_le_bytes());
        buffer.extend_from_slice(&clamp(line.content_span.offset).to_le_bytes());
        buffer.extend_from_slice(&clamp(line.content_span.length).to_le_bytes());
        buffer.push(match line.ending {
            LineEnding::Lf => 0,
            LineEnding::Crlf => 1,
            LineEnding::Cr => 2,
            LineEnding::None => 3,
        });
        buffer.push(match line.kind {
            RawLineKind::Blank => 0,
            RawLineKind::Data => 1,
            RawLineKind::SectionMarker(_) => 2,
            RawLineKind::EntityTerminator => 3,
            RawLineKind::FileTerminator => 4,
        });
        buffer.extend_from_slice(&0u16.to_le_bytes());
        buffer.extend_from_slice(&line.kind.section_number().unwrap_or(u32::MAX).to_le_bytes());
    }
    PyBytes::new(py, &buffer)
}

fn record_dict<'py>(py: Python<'py>, record: &RawRecord) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("index", record.index)?;
    result.set_item("section_index", record.section_index)?;
    result.set_item("section_number", record.section_number)?;
    result.set_item("span", span_dict(py, record.span)?)?;
    result.set_item("payload_span", span_dict(py, record.payload_span)?)?;
    if let Some(span) = record.terminator_span {
        result.set_item("terminator_span", span_dict(py, span)?)?;
    } else {
        result.set_item("terminator_span", py.None())?;
    }
    result.set_item("termination", record.termination.as_str())?;
    result.set_item("record_type", record.record_type.as_deref())?;
    Ok(result)
}

fn section_dict<'py>(py: Python<'py>, section: &RawSection) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("index", section.index)?;
    result.set_item("number", section.number)?;
    result.set_item("span", span_dict(py, section.span)?)?;
    result.set_item("marker_span", span_dict(py, section.marker_span)?)?;
    result.set_item("body_span", span_dict(py, section.body_span)?)?;
    result.set_item("first_record", section.first_record)?;
    result.set_item("record_count", section.record_count)?;
    Ok(result)
}

fn diagnostic_dict<'py>(py: Python<'py>, diagnostic: &Diagnostic) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("severity", diagnostic.severity.as_str())?;
    result.set_item("code", diagnostic.code)?;
    result.set_item("message", &diagnostic.message)?;
    result.set_item("span", span_dict(py, diagnostic.span)?)?;
    result.set_item("action", diagnostic.action)?;
    Ok(result)
}

fn span_dict(py: Python<'_>, span: SourceSpan) -> PyResult<Bound<'_, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("offset", span.offset)?;
    result.set_item("length", span.length)?;
    result.set_item("start_line", span.start_line)?;
    result.set_item("end_line", span.end_line)?;
    Ok(result)
}

fn core_error_to_python(error: CoreMiError) -> PyErr {
    let message = error.to_string();
    if error.is_encoding_error() {
        PyValueError::new_err(message)
    } else if error.is_limit_error() {
        MiLimitError::new_err(message)
    } else if error.is_unsupported_error() {
        UnsupportedMiError::new_err(message)
    } else {
        InvalidMiError::new_err(message)
    }
}

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add(
        "DEFAULT_MAX_FILE_SIZE_BYTES",
        ezmi2d_core::DEFAULT_MAX_FILE_SIZE_BYTES,
    )?;
    module.add("DEFAULT_MAX_LINES", ezmi2d_core::DEFAULT_MAX_LINES)?;
    module.add("DEFAULT_MAX_SECTIONS", ezmi2d_core::DEFAULT_MAX_SECTIONS)?;
    module.add("DEFAULT_MAX_RECORDS", ezmi2d_core::DEFAULT_MAX_RECORDS)?;
    module.add(
        "DEFAULT_MAX_LINE_SIZE_BYTES",
        ezmi2d_core::DEFAULT_MAX_LINE_SIZE_BYTES,
    )?;
    module.add(
        "DEFAULT_MAX_RECORD_SIZE_BYTES",
        ezmi2d_core::DEFAULT_MAX_RECORD_SIZE_BYTES,
    )?;
    module.add(
        "DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES",
        ezmi2d_core::DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES,
    )?;
    module.add(
        "DEFAULT_MAX_COMPRESSION_RATIO",
        ezmi2d_core::DEFAULT_MAX_COMPRESSION_RATIO,
    )?;
    module.add("MiError", py.get_type::<MiError>())?;
    module.add("InvalidMiError", py.get_type::<InvalidMiError>())?;
    module.add("UnsupportedMiError", py.get_type::<UnsupportedMiError>())?;
    module.add("MiLimitError", py.get_type::<MiLimitError>())?;
    module.add_function(wrap_pyfunction!(core_version, module)?)?;
    module.add_function(wrap_pyfunction!(detect_format_bytes, module)?)?;
    module.add_function(wrap_pyfunction!(scan_mi_records, module)?)?;
    module.add_function(wrap_pyfunction!(read_legacy_document, module)?)?;
    Ok(())
}
