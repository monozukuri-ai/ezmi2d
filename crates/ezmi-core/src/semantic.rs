use std::borrow::Cow;
use std::collections::{BTreeMap, BTreeSet};

use crate::model::{
    ArcEntity, AssemblyEntity, AssemblyInstance, BSplineEntity, BSplineSample, Bounds2,
    CircleEntity, EncodingInfo, EntityHeader, EntityId, GlobalInfo, GraphicHeader, LineEntity,
    Part, Point2, PointEntity, PropertyEntity, SemanticDocument, SemanticEntity, StructuredEntity,
    TextEntity, TextValue, UnsupportedEntity,
};
use crate::{
    scan_input, Diagnostic, DiagnosticSeverity, EncodingSource, MiError, RawDocument, RawRecord,
    RawSection, ScanOptions, SourceSpan, TextEncoding,
};

const LEGACY_GLOBAL_MIN_FIELDS: usize = 45;
/// Bound variable-prefix probing to a small constant instead of record length.
/// Verified layouts start at field 7 (legacy) or fields 14 through 19 (modern).
const MAX_BSPLINE_LAYOUT_START: usize = 64;

#[derive(Debug, Clone)]
struct DeclaredEncoding {
    name: String,
    span: SourceSpan,
}

#[derive(Debug, Clone, Copy)]
struct TextCandidate<'a> {
    bytes: &'a [u8],
    span: SourceSpan,
}

/// A semantic document together with the logical MI bytes addressed by its raw spans.
#[derive(Debug)]
pub struct SemanticInput<'a> {
    pub source: Cow<'a, [u8]>,
    pub document: SemanticDocument,
}

/// Parse verified legacy geometry and text while retaining the complete raw scan.
pub fn read(data: &[u8], options: ScanOptions) -> Result<SemanticDocument, MiError> {
    read_with_encoding(data, options, None)
}

/// Parse semantic MI data using an optional user-selected text encoding.
pub fn read_with_encoding(
    data: &[u8],
    options: ScanOptions,
    encoding_override: Option<&str>,
) -> Result<SemanticDocument, MiError> {
    Ok(read_input_with_encoding(data, options, encoding_override)?.document)
}

/// Parse semantic MI data and retain the logical source bytes used by all spans.
pub fn read_input_with_encoding<'a>(
    data: &'a [u8],
    options: ScanOptions,
    encoding_override: Option<&str>,
) -> Result<SemanticInput<'a>, MiError> {
    let scanned = scan_input(data, options)?;
    let document =
        read_scanned_with_encoding(scanned.source.as_ref(), scanned.document, encoding_override)?;
    Ok(SemanticInput {
        source: scanned.source,
        document,
    })
}

fn read_scanned_with_encoding(
    data: &[u8],
    raw: RawDocument,
    encoding_override: Option<&str>,
) -> Result<SemanticDocument, MiError> {
    let mut diagnostics = raw.diagnostics.clone();
    let encoding = detect_text_encoding(data, &raw, encoding_override, &mut diagnostics)?;
    let global = parse_global(data, &raw, &encoding, &mut diagnostics);
    let toc_last_entity = parse_toc_last(data, &raw, &mut diagnostics);
    let (mut parts, section_parts) = parse_parts(data, &raw, &encoding, &mut diagnostics);

    let mut entities = Vec::new();
    for record in &raw.records {
        let Some(mi_type) = record.record_type.as_deref() else {
            continue;
        };
        let part_index = section_parts.get(record.section_index).copied().flatten();
        if let Some(entity) = parse_entity(
            data,
            record,
            mi_type,
            part_index,
            &encoding,
            &mut diagnostics,
        ) {
            entities.push(entity);
        }
    }

    let entity_index = build_entity_index(&entities, &raw, &mut diagnostics);
    let sheet_part_indices = bind_part_structure(
        &mut parts,
        &mut entities,
        &entity_index,
        &raw,
        &mut diagnostics,
    );
    resolve_references(&mut entities, &entity_index, &raw, &mut diagnostics);
    populate_parts(&mut parts, &entities);
    validate_toc_last(toc_last_entity, &entities, &raw, &mut diagnostics);
    let root_part_indices = parts
        .iter()
        .filter(|part| part.parent_part_indices.is_empty())
        .map(|part| part.index)
        .collect::<Vec<_>>();
    let top_part_index = (root_part_indices.len() == 1)
        .then(|| root_part_indices[0])
        .or_else(|| {
            parts
                .iter()
                .position(|part| part.name.bytes.eq_ignore_ascii_case(b"top"))
        })
        .or_else(|| root_part_indices.first().copied())
        .or_else(|| (!parts.is_empty()).then_some(0));

    Ok(SemanticDocument {
        raw,
        encoding,
        global,
        toc_last_entity,
        parts,
        top_part_index,
        root_part_indices,
        sheet_part_indices,
        entities,
        entity_index,
        diagnostics,
    })
}

fn detect_text_encoding(
    data: &[u8],
    raw: &RawDocument,
    encoding_override: Option<&str>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Result<EncodingInfo, MiError> {
    let declared = declared_encoding(data, raw, diagnostics);
    if let Some(label) = encoding_override {
        let Some(encoding) = TextEncoding::for_label(label) else {
            return Err(MiError::UnsupportedTextEncoding {
                encoding: label.to_owned(),
            });
        };
        if declared.as_ref().is_some_and(|value| {
            TextEncoding::for_label(&value.name).is_some_and(|value| value != encoding)
        }) {
            diagnostics.push(encoding_conflict_diagnostic(
                declared.as_ref().expect("checked above").span,
                format!(
                    "text encoding override {} takes precedence over declared encoding {}",
                    encoding.name(),
                    declared.as_ref().expect("checked above").name
                ),
            ));
        }
        return Ok(EncodingInfo {
            encoding: Some(encoding),
            source: EncodingSource::Override,
            declared_name: declared.map(|value| value.name),
        });
    }

    if raw.format.utf8_bom {
        if declared.as_ref().is_some_and(|value| {
            TextEncoding::for_label(&value.name).is_some_and(|value| value != TextEncoding::Utf8)
        }) {
            diagnostics.push(encoding_conflict_diagnostic(
                declared.as_ref().expect("checked above").span,
                "UTF-8 BOM takes precedence over a conflicting encoding declaration".to_owned(),
            ));
        }
        return Ok(EncodingInfo {
            encoding: Some(TextEncoding::Utf8),
            source: EncodingSource::Utf8Bom,
            declared_name: declared.map(|value| value.name),
        });
    }

    let version = raw_global_version(data, raw);
    if version.as_deref().is_some_and(mi_version_is_utf8) {
        if declared.as_ref().is_some_and(|value| {
            TextEncoding::for_label(&value.name).is_some_and(|value| value != TextEncoding::Utf8)
        }) {
            diagnostics.push(encoding_conflict_diagnostic(
                declared.as_ref().expect("checked above").span,
                format!(
                    "MI version {} requires UTF-8 and takes precedence over declared encoding {}",
                    version.as_deref().unwrap_or_default(),
                    declared.as_ref().expect("checked above").name
                ),
            ));
        }
        return Ok(EncodingInfo {
            encoding: Some(TextEncoding::Utf8),
            source: EncodingSource::MiVersion,
            declared_name: declared.map(|value| value.name),
        });
    }

    if let Some(declared) = declared {
        if let Some(encoding) = TextEncoding::for_label(&declared.name) {
            return Ok(EncodingInfo {
                encoding: Some(encoding),
                source: EncodingSource::Declared,
                declared_name: Some(declared.name),
            });
        }
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_UNSUPPORTED_DECLARED_ENCODING",
            message: format!("unsupported encoding declaration: {}", declared.name),
            span: declared.span,
            action: Some(
                "pass a supported encoding override to read() and preserve the source bytes",
            ),
        });
        return Ok(EncodingInfo {
            encoding: None,
            source: EncodingSource::Declared,
            declared_name: Some(declared.name),
        });
    }

    let candidates = collect_text_candidates(data, raw);
    let non_ascii = candidates
        .iter()
        .copied()
        .filter(|candidate| !candidate.bytes.is_ascii())
        .collect::<Vec<_>>();
    if non_ascii.is_empty() {
        return Ok(EncodingInfo {
            encoding: None,
            source: EncodingSource::AsciiOnly,
            declared_name: None,
        });
    }

    let utf8_valid = non_ascii
        .iter()
        .all(|candidate| TextEncoding::Utf8.decode(candidate.bytes).is_ok());
    let shift_jis_valid = non_ascii
        .iter()
        .all(|candidate| TextEncoding::ShiftJis.decode(candidate.bytes).is_ok());
    let has_shift_jis_pair = non_ascii
        .iter()
        .any(|candidate| contains_shift_jis_pair(candidate.bytes));
    let inferred = if utf8_valid {
        Some(TextEncoding::Utf8)
    } else if shift_jis_valid && has_shift_jis_pair {
        Some(TextEncoding::ShiftJis)
    } else {
        None
    };

    if let Some(encoding) = inferred {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Info,
            code: "MI_ENCODING_GUESSED",
            message: format!(
                "legacy MI text encoding was inferred as {} from known text fields",
                encoding.name()
            ),
            span: non_ascii[0].span,
            action: Some("pass encoding= explicitly when the producing locale is known"),
        });
        Ok(EncodingInfo {
            encoding: Some(encoding),
            source: EncodingSource::Heuristic,
            declared_name: None,
        })
    } else {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_ENCODING_UNDETERMINED",
            message: "legacy MI text contains non-ASCII bytes but its encoding is undetermined"
                .to_owned(),
            span: non_ascii[0].span,
            action: Some("pass encoding='shift_jis', 'hp-roman8', or 'utf-8' to read()"),
        });
        Ok(EncodingInfo {
            encoding: None,
            source: EncodingSource::Undetermined,
            declared_name: None,
        })
    }
}

fn declared_encoding(
    data: &[u8],
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<DeclaredEncoding> {
    let mut declarations = Vec::new();
    for section in raw.sections.iter().filter(|section| section.number == 1) {
        for (index, field) in
            split_lines(&data[section.body_span.offset..section.body_span.end_offset()])
                .into_iter()
                .enumerate()
        {
            let trimmed = trim_ascii(field);
            let Some(colon) = trimmed.iter().position(|byte| *byte == b':') else {
                continue;
            };
            if !trimmed[..colon].eq_ignore_ascii_case(b"ENCODING") {
                continue;
            }
            let label = trim_ascii(&trimmed[colon + 1..]);
            let name = String::from_utf8_lossy(label).into_owned();
            declarations.push(DeclaredEncoding {
                name,
                span: field_source_span(data, label, section.body_span.start_line + index),
            });
        }
    }
    let first = declarations.first()?.clone();
    for declaration in declarations.iter().skip(1) {
        if declaration.name.eq_ignore_ascii_case(&first.name) {
            continue;
        }
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_CONFLICTING_ENCODING_DECLARATION",
            message: format!(
                "encoding declaration {} conflicts with the first declaration {}",
                declaration.name, first.name
            ),
            span: declaration.span,
            action: Some("remove conflicting declarations or pass an explicit encoding override"),
        });
    }
    Some(first)
}

fn encoding_conflict_diagnostic(span: SourceSpan, message: String) -> Diagnostic {
    Diagnostic {
        severity: DiagnosticSeverity::Info,
        code: "MI_ENCODING_CONFLICT",
        message,
        span,
        action: Some("verify the file producer and use an explicit encoding override if needed"),
    }
}

fn raw_global_version(data: &[u8], raw: &RawDocument) -> Option<String> {
    let section = raw.sections.iter().find(|section| section.number == 3)?;
    let fields = split_lines(&data[section.body_span.offset..section.body_span.end_offset()]);
    ascii_field(&fields, 11)
}

fn mi_version_is_utf8(version: &str) -> bool {
    let mut parts = version.trim().split('.');
    let Some(major) = parts.next().and_then(|value| value.parse::<u32>().ok()) else {
        return false;
    };
    let minor = parts
        .next()
        .and_then(|value| value.parse::<u32>().ok())
        .unwrap_or_default();
    (major, minor) >= (3, 20)
}

fn collect_text_candidates<'a>(data: &'a [u8], raw: &RawDocument) -> Vec<TextCandidate<'a>> {
    let mut result = Vec::new();
    for section in &raw.sections {
        let fields = split_lines(&data[section.body_span.offset..section.body_span.end_offset()]);
        match section.number {
            3 => {
                for index in [0, 7, 8, 10] {
                    push_text_candidate(
                        data,
                        &fields,
                        index,
                        section.body_span.start_line,
                        &mut result,
                    );
                }
            }
            6 => {
                if let Some((index, _)) = fields
                    .iter()
                    .enumerate()
                    .find(|(_, field)| !trim_ascii(field).is_empty())
                {
                    push_text_candidate(
                        data,
                        &fields,
                        index,
                        section.body_span.start_line,
                        &mut result,
                    );
                }
            }
            _ => {}
        }
    }
    for record in &raw.records {
        let Some(mi_type) = record.record_type.as_deref() else {
            continue;
        };
        let fields =
            split_lines(&data[record.payload_span.offset..record.payload_span.end_offset()]);
        let Some(type_index) = fields
            .iter()
            .position(|field| trim_ascii(field) == mi_type.as_bytes())
        else {
            continue;
        };
        let entity_fields = &fields[type_index..];
        let start_line = record.payload_span.start_line + type_index;
        match mi_type {
            "ASSE" => {
                if let Some(name_index) = assembly_name_index(entity_fields) {
                    push_text_candidate(data, entity_fields, name_index, start_line, &mut result);
                }
            }
            "TEX" => {
                push_text_candidate(data, entity_fields, 19, start_line, &mut result);
                push_text_candidate(data, entity_fields, 28, start_line, &mut result);
            }
            _ => {}
        }
    }
    result
}

fn push_text_candidate<'a>(
    data: &'a [u8],
    fields: &[&'a [u8]],
    index: usize,
    start_line: usize,
    result: &mut Vec<TextCandidate<'a>>,
) {
    if let Some(field) = fields.get(index) {
        result.push(TextCandidate {
            bytes: field,
            span: field_source_span(data, field, start_line + index),
        });
    }
}

fn contains_shift_jis_pair(bytes: &[u8]) -> bool {
    bytes.windows(2).any(|pair| {
        matches!(pair[0], 0x81..=0x9f | 0xe0..=0xfc) && matches!(pair[1], 0x40..=0x7e | 0x80..=0xfc)
    })
}

fn parse_global(
    data: &[u8],
    raw: &RawDocument,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<GlobalInfo> {
    let Some(section) = raw.sections.iter().find(|section| section.number == 3) else {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_MISSING_GLOBAL_SECTION",
            message: "MI section #~3 is missing".to_owned(),
            span: SourceSpan::new(0, 0, 1, 1),
            action: Some("verify that the input contains a complete global section"),
        });
        return None;
    };
    let fields = split_lines(&data[section.body_span.offset..section.body_span.end_offset()]);
    if fields.len() < LEGACY_GLOBAL_MIN_FIELDS {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_GLOBAL_RECORD_TOO_SHORT",
            message: format!(
                "legacy global section has {} fields; at least {LEGACY_GLOBAL_MIN_FIELDS} are required",
                fields.len()
            ),
            span: section.body_span,
            action: Some("inspect the global section or obtain the matching MI version reference"),
        });
    }

    let version = ascii_field(&fields, 11);
    if version.as_deref().is_some_and(|value| value != "2.10") {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Info,
            code: "MI_GLOBAL_LAYOUT_UNVERIFIED",
            message: format!(
                "global metadata field positions are verified for MI 2.10, not {}",
                version.as_deref().unwrap_or_default()
            ),
            span: section.body_span,
            action: Some("treat parsed global metadata as provisional for this MI version"),
        });
    }

    let extents = parse_extents(&fields).or_else(|| {
        if fields.len() >= 17 {
            diagnostics.push(invalid_global_field(
                section,
                "drawing extents at fields 13 through 16 are not finite numbers",
            ));
        }
        None
    });
    let transform_values = parse_transform(&fields).or_else(|| {
        if fields.len() >= LEGACY_GLOBAL_MIN_FIELDS {
            diagnostics.push(invalid_global_field(
                section,
                "transform fields 29 through 44 are not finite numbers",
            ));
        }
        None
    });

    Some(GlobalInfo {
        section_index: section.index,
        drawing_name: decoded_text_field(
            data,
            &fields,
            0,
            section.body_span.start_line,
            encoding,
            diagnostics,
            "global drawing name",
        ),
        creation_date: decoded_text_field(
            data,
            &fields,
            7,
            section.body_span.start_line,
            encoding,
            diagnostics,
            "global creation date",
        ),
        creation_time: decoded_text_field(
            data,
            &fields,
            8,
            section.body_span.start_line,
            encoding,
            diagnostics,
            "global creation time",
        ),
        producer: decoded_text_field(
            data,
            &fields,
            10,
            section.body_span.start_line,
            encoding,
            diagnostics,
            "global producer",
        ),
        version,
        dimension: ascii_field(&fields, 12),
        extents,
        paper_size: ascii_field(&fields, 20),
        drawing_scale: finite_f64_field(&fields, 21),
        unit: ascii_field(&fields, 22),
        angle_unit: ascii_field(&fields, 23),
        transform_values,
    })
}

fn parse_toc_last(
    data: &[u8],
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<EntityId> {
    let section = raw.sections.iter().find(|section| section.number == 2)?;
    let fields = split_lines(&data[section.body_span.offset..section.body_span.end_offset()]);
    let line = fields
        .iter()
        .map(|field| trim_ascii(field))
        .find(|field| field.starts_with(b"LAST:"))?;
    let Some(value) = parse_u64(line.strip_prefix(b"LAST:").unwrap_or_default()) else {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_INVALID_TOC_LAST",
            message: "table-of-contents LAST value is not an entity ID".to_owned(),
            span: section.body_span,
            action: Some("inspect the LAST entry in section #~2"),
        });
        return None;
    };
    Some(value)
}

fn parse_parts(
    data: &[u8],
    raw: &RawDocument,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
) -> (Vec<Part>, Vec<Option<usize>>) {
    let mut parts = Vec::new();
    let mut section_parts = vec![None; raw.sections.len()];
    let mut current_part = None;

    for section in &raw.sections {
        if section.number == 6 {
            let fields =
                split_lines(&data[section.body_span.offset..section.body_span.end_offset()]);
            let name_field = fields
                .iter()
                .enumerate()
                .find(|(_, field)| !trim_ascii(field).is_empty());
            let (name_field_index, name_bytes) = name_field
                .map(|(field_index, field)| (field_index, *field))
                .unwrap_or((0, b""));
            if name_bytes.is_empty() {
                diagnostics.push(Diagnostic {
                    severity: DiagnosticSeverity::Warning,
                    code: "MI_EMPTY_PART_NAME",
                    message: "part definition section #~6 has no name".to_owned(),
                    span: section.body_span,
                    action: Some("inspect the part definition preceding its entity sections"),
                });
            }
            let index = parts.len();
            parts.push(Part {
                index,
                name: decode_text_value(
                    data,
                    name_bytes,
                    section.body_span.start_line + name_field_index,
                    encoding,
                    diagnostics,
                    "part name",
                ),
                definition_section_index: section.index,
                point_ids: Vec::new(),
                graphic_entity_ids: Vec::new(),
                annotation_entity_ids: Vec::new(),
                unsupported_entity_ids: Vec::new(),
                source_entity_ids: Vec::new(),
                assembly_id: None,
                child_part_indices: Vec::new(),
                parent_part_indices: Vec::new(),
            });
            current_part = Some(index);
            section_parts[section.index] = current_part;
        } else if matches!(section.number, 61 | 62 | 63 | 71 | 72 | 81 | 82) {
            section_parts[section.index] = current_part;
            if current_part.is_none() && section.record_count > 0 {
                diagnostics.push(Diagnostic {
                    severity: DiagnosticSeverity::Warning,
                    code: "MI_ENTITY_SECTION_OUTSIDE_PART",
                    message: format!(
                        "section #~{} contains entities before any #~6 part definition",
                        section.number
                    ),
                    span: section.span,
                    action: Some("inspect the assembly and part section ordering"),
                });
            }
        }
    }

    (parts, section_parts)
}

fn parse_entity(
    data: &[u8],
    record: &RawRecord,
    mi_type: &str,
    part_index: Option<usize>,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<SemanticEntity> {
    let all_fields =
        split_lines(&data[record.payload_span.offset..record.payload_span.end_offset()]);
    let type_index = all_fields
        .iter()
        .position(|field| trim_ascii(field) == mi_type.as_bytes())?;
    let fields = &all_fields[type_index..];
    let Some(id) = fields.get(1).and_then(|field| parse_u64(field)) else {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_INVALID_ENTITY_ID",
            message: format!("{mi_type} record has no valid entity ID"),
            span: record.payload_span,
            action: Some("inspect the entity ID immediately after the record type"),
        });
        return None;
    };
    let header = EntityHeader {
        id,
        raw_record_index: record.index,
        part_index,
    };

    let parsed = match mi_type {
        "P" => parse_point(fields, header.clone()),
        "LIN" => parse_line(fields, header.clone()),
        "ARC" => parse_arc(fields, header.clone()),
        "FIL" => parse_fillet(fields, header.clone()),
        "BSPL" => parse_bspline(fields, header.clone()),
        "CIR" => parse_circle(fields, header.clone()),
        "TEX" => parse_text(
            data,
            fields,
            header.clone(),
            record.payload_span.start_line + type_index,
            encoding,
            diagnostics,
        ),
        "PSTAT" | "ASSP" | "DTA" | "DTF" | "DLA" | "DDA" | "DAF" | "HAPP" => {
            parse_property(fields, header.clone(), mi_type)
        }
        "DTV" => parse_structured(fields, header.clone(), mi_type, 10)
            .map(SemanticEntity::DimensionTolerance),
        "LED" => parse_structured(fields, header.clone(), mi_type, 18).map(SemanticEntity::Leader),
        "HAT" => parse_structured(fields, header.clone(), mi_type, 12).map(SemanticEntity::Hatch),
        "SYML" => parse_structured(fields, header.clone(), mi_type, 5).map(SemanticEntity::Symbol),
        "DANG" => {
            parse_structured(fields, header.clone(), mi_type, 75).map(SemanticEntity::Dimension)
        }
        "DCHMF" => {
            parse_structured(fields, header.clone(), mi_type, 63).map(SemanticEntity::Dimension)
        }
        "DDIA" => {
            parse_structured(fields, header.clone(), mi_type, 64).map(SemanticEntity::Dimension)
        }
        "DRAD" => {
            parse_structured(fields, header.clone(), mi_type, 56).map(SemanticEntity::Dimension)
        }
        "DSGL" => {
            parse_structured(fields, header.clone(), mi_type, 73).map(SemanticEntity::Dimension)
        }
        "ASSE" => parse_assembly(
            data,
            fields,
            header.clone(),
            record.payload_span.start_line + type_index,
            encoding,
            diagnostics,
        ),
        _ => {
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Info,
                code: "MI_UNSUPPORTED_ENTITY",
                message: format!("{mi_type} entity {id} is retained as an unsupported entity"),
                span: record.payload_span,
                action: Some("use raw_record to inspect fields not yet exposed semantically"),
            });
            Ok(SemanticEntity::Unsupported(UnsupportedEntity {
                entity: header.clone(),
                mi_type: mi_type.to_owned(),
            }))
        }
    };

    match parsed {
        Ok(entity) => Some(entity),
        Err(issue) => {
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Warning,
                code: "MI_INVALID_ENTITY_RECORD",
                message: format!("{mi_type} entity {id} cannot be decoded: {issue}"),
                span: record.payload_span,
                action: Some("inspect the raw record and MI version-specific field layout"),
            });
            Some(SemanticEntity::Unsupported(UnsupportedEntity {
                entity: header,
                mi_type: mi_type.to_owned(),
            }))
        }
    }
}

fn parse_point(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    require_fields(fields, 4, "P")?;
    Ok(SemanticEntity::Point(PointEntity {
        entity,
        location: Point2::new(required_f64(fields, 2, "x")?, required_f64(fields, 3, "y")?),
    }))
}

fn parse_property(
    fields: &[&[u8]],
    entity: EntityHeader,
    mi_type: &str,
) -> Result<SemanticEntity, String> {
    require_fields(fields, 4, mi_type)?;
    Ok(SemanticEntity::Property(PropertyEntity {
        entity,
        mi_type: mi_type.to_owned(),
        values: fields.iter().skip(2).map(|field| field.to_vec()).collect(),
    }))
}

fn parse_structured(
    fields: &[&[u8]],
    entity: EntityHeader,
    mi_type: &str,
    minimum_fields: usize,
) -> Result<StructuredEntity, String> {
    require_fields(fields, minimum_fields, mi_type)?;
    Ok(StructuredEntity {
        entity,
        mi_type: mi_type.to_owned(),
        values: fields.iter().skip(2).map(|field| field.to_vec()).collect(),
    })
}

fn parse_assembly(
    data: &[u8],
    fields: &[&[u8]],
    entity: EntityHeader,
    start_line: usize,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
) -> Result<SemanticEntity, String> {
    require_fields(fields, 5, "ASSE")?;
    let property_count = required_usize(fields, 2, "assembly property count")?;
    let name_index = assembly_name_index(fields)
        .ok_or_else(|| "assembly property count exceeds the available fields".to_owned())?;
    require_fields(fields, name_index + 1, "ASSE")?;
    let property_ids = (0..property_count)
        .map(|offset| required_u64(fields, 3 + offset, "assembly property pointer"))
        .collect::<Result<Vec<_>, _>>()?;
    let instances = parse_assembly_instances(fields, name_index)?;
    Ok(SemanticEntity::Assembly(AssemblyEntity {
        entity,
        property_ids,
        part_name: decoded_text_field(
            data,
            fields,
            name_index,
            start_line,
            encoding,
            diagnostics,
            "assembly part name",
        ),
        instances,
        definition_part_index: None,
        values: fields.iter().skip(2).map(|field| field.to_vec()).collect(),
    }))
}

fn parse_assembly_instances(
    fields: &[&[u8]],
    name_index: usize,
) -> Result<Vec<AssemblyInstance>, String> {
    // Legacy ASSE records end after three placement values and have no serialized children.
    let child_count_index = name_index + 6;
    if fields.len() <= child_count_index {
        return Ok(Vec::new());
    }
    let child_count = required_usize(fields, child_count_index, "assembly child count")?;
    if child_count == 0 {
        if fields.len() != child_count_index + 1 {
            return Err("ASSE zero-child layout has unexpected trailing fields".to_owned());
        }
        return Ok(Vec::new());
    }

    let mut cursor = child_count_index + 1;
    let minimum_child_fields = child_count
        .checked_mul(14)
        .and_then(|value| value.checked_add(child_count - 1))
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| "assembly child count overflows record size".to_owned())?;
    if fields.len().saturating_sub(cursor) < minimum_child_fields {
        return Err(format!(
            "ASSE declares {child_count} children but the record is too short"
        ));
    }
    let mut instances = Vec::with_capacity(child_count);
    for child_index in 0..child_count {
        let relation_value = if child_index == 0 {
            None
        } else {
            let value = fields
                .get(cursor)
                .ok_or_else(|| "ASSE child separator is missing".to_owned())?;
            cursor += 1;
            Some(value.to_vec())
        };
        require_fields(fields, cursor + 4, "ASSE child")?;
        let definition_values = [
            fields[cursor].to_vec(),
            fields[cursor + 1].to_vec(),
            fields[cursor + 2].to_vec(),
        ];
        let member_count = required_usize(fields, cursor + 3, "assembly child member count")?;
        cursor += 4;
        let members_end = cursor
            .checked_add(member_count)
            .ok_or_else(|| "assembly child member count overflows field index".to_owned())?;
        require_fields(fields, members_end + 10, "ASSE child")?;
        let member_ids = (cursor..members_end)
            .map(|index| required_u64(fields, index, "assembly child member pointer"))
            .collect::<Result<Vec<_>, _>>()?;
        cursor = members_end;
        let assembly_id = required_u64(fields, cursor, "child assembly pointer")?;
        cursor += 1;
        let transform_values = parse_f64_array::<9>(fields, cursor, "assembly child transform")?;
        cursor += 9;
        instances.push(AssemblyInstance {
            relation_value,
            definition_values,
            member_ids,
            assembly_id,
            transform_values,
            target_part_index: None,
            is_sheet: false,
        });
    }
    if fields.len() != cursor + 1 {
        return Err(format!(
            "ASSE child layout leaves {} unexpected fields",
            fields.len().saturating_sub(cursor + 1)
        ));
    }
    required_usize(fields, cursor, "assembly definition ordinal")?;
    Ok(instances)
}

fn parse_text(
    data: &[u8],
    fields: &[&[u8]],
    entity: EntityHeader,
    start_line: usize,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
) -> Result<SemanticEntity, String> {
    require_fields(fields, 30, "TEX")?;
    let transform_values = parse_f64_array::<9>(fields, 8, "text transform")?;
    let size_values = parse_f64_array::<2>(fields, 22, "text size")?;
    let id = entity.id;
    Ok(SemanticEntity::Text(TextEntity {
        graphic: parse_graphic_header(fields, entity)?,
        transform_values,
        font_name: decoded_text_field(
            data,
            fields,
            19,
            start_line,
            encoding,
            diagnostics,
            &format!("TEX entity {id} font name"),
        )
        .expect("field count was checked"),
        size_values,
        content: decoded_text_field(
            data,
            fields,
            28,
            start_line,
            encoding,
            diagnostics,
            &format!("TEX entity {id} content"),
        )
        .expect("field count was checked"),
        values: fields.iter().skip(2).map(|field| field.to_vec()).collect(),
    }))
}

fn parse_line(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    require_fields(fields, 9, "LIN")?;
    Ok(SemanticEntity::Line(LineEntity {
        graphic: parse_graphic_header(fields, entity)?,
        start_id: required_u64(fields, 7, "start point")?,
        end_id: required_u64(fields, 8, "end point")?,
        start: None,
        end: None,
    }))
}

fn parse_arc(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    require_fields(fields, 11, "ARC")?;
    Ok(SemanticEntity::Arc(ArcEntity {
        graphic: parse_graphic_header(fields, entity)?,
        center_id: required_u64(fields, 7, "center point")?,
        start_id: required_u64(fields, 8, "start point")?,
        end_id: required_u64(fields, 9, "end point")?,
        orientation: required_i64(fields, 10, "orientation")?,
        center: None,
        start: None,
        end: None,
    }))
}

fn parse_fillet(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    let SemanticEntity::Arc(arc) = parse_arc(fields, entity)? else {
        unreachable!("parse_arc always returns an arc")
    };
    Ok(SemanticEntity::Fillet(arc))
}

fn parse_bspline(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    require_fields(fields, 16, "BSPL")?;
    let candidate_end = fields
        .len()
        .saturating_sub(8)
        .min(MAX_BSPLINE_LAYOUT_START.saturating_add(1));
    let layout_starts = (2..candidate_end)
        .filter(|start| bspline_layout_end(fields, *start).is_some_and(|end| end == fields.len()))
        .collect::<Vec<_>>();
    let [layout_start] = layout_starts.as_slice() else {
        return Err(format!(
            "BSPL has {} matching spline layouts; expected exactly one",
            layout_starts.len()
        ));
    };
    let layout_start = *layout_start;
    let order = required_usize(fields, layout_start, "spline order")?;
    let parameter_max = required_f64(fields, layout_start + 3, "spline parameter maximum")?;
    let start_id = required_u64(fields, layout_start + 4, "spline start point")?;
    let end_id = required_u64(fields, layout_start + 5, "spline end point")?;
    let control_count = required_usize(fields, layout_start + 6, "spline control point count")?;
    if order == 0 || control_count < order {
        return Err(format!(
            "spline control point count {control_count} is smaller than order {order}"
        ));
    }
    let control_start = layout_start + 7;
    let control_end = control_start + control_count;
    let control_point_ids = (control_start..control_end)
        .map(|index| required_u64(fields, index, "spline control point"))
        .collect::<Result<Vec<_>, _>>()?;
    let knot_count = required_usize(fields, control_end, "spline knot count")?;
    if knot_count != control_count + order {
        return Err(format!(
            "spline knot count {knot_count} does not equal control count {control_count} + order {order}"
        ));
    }
    let knot_start = control_end + 1;
    let knot_end = knot_start + knot_count;
    let knots = (knot_start..knot_end)
        .map(|index| required_f64(fields, index, "spline knot"))
        .collect::<Result<Vec<_>, _>>()?;
    if knots.windows(2).any(|pair| pair[0] > pair[1]) {
        return Err("spline knots are not nondecreasing".to_owned());
    }
    let sample_count = required_usize(fields, knot_end, "spline sample count")?;
    let mut samples = Vec::with_capacity(sample_count);
    let mut cursor = knot_end + 1;
    for _ in 0..sample_count {
        samples.push(BSplineSample {
            point_id: required_u64(fields, cursor, "spline sample point")?,
            parameter: required_f64(fields, cursor + 1, "spline sample parameter")?,
            definition_values: parse_f64_array::<5>(
                fields,
                cursor + 2,
                "spline sample definition",
            )?,
            point: None,
        });
        cursor += 7;
    }
    debug_assert_eq!(cursor, fields.len());

    let graphic = (layout_start == 7)
        .then(|| parse_graphic_header(fields, entity.clone()))
        .transpose()?;
    Ok(SemanticEntity::BSpline(BSplineEntity {
        entity,
        graphic,
        prefix_values: fields[2..layout_start]
            .iter()
            .map(|field| field.to_vec())
            .collect(),
        order,
        definition_values: [
            fields[layout_start + 1].to_vec(),
            fields[layout_start + 2].to_vec(),
        ],
        parameter_max,
        start_id,
        end_id,
        start: None,
        end: None,
        control_point_ids,
        control_points: vec![None; control_count],
        knots,
        samples,
        values: fields.iter().skip(2).map(|field| field.to_vec()).collect(),
    }))
}

fn assembly_name_index(fields: &[&[u8]]) -> Option<usize> {
    let property_count = parse_usize(fields.get(2)?)?;
    3usize
        .checked_add(property_count)
        .filter(|index| *index < fields.len())
}

fn bspline_layout_end(fields: &[&[u8]], start: usize) -> Option<usize> {
    let order = required_usize(fields, start, "spline order").ok()?;
    if !(1..=16).contains(&order) {
        return None;
    }
    parse_i64(fields.get(start + 1)?)?;
    parse_i64(fields.get(start + 2)?)?;
    finite_f64_field(fields, start + 3)?;
    parse_u64(fields.get(start + 4)?)?;
    parse_u64(fields.get(start + 5)?)?;
    let control_count = required_usize(fields, start + 6, "spline control point count").ok()?;
    if control_count < order {
        return None;
    }
    let control_end = start.checked_add(7)?.checked_add(control_count)?;
    for field in fields.get(start + 7..control_end)? {
        parse_u64(field)?;
    }
    let knot_count = parse_usize(fields.get(control_end)?)?;
    if knot_count != control_count.checked_add(order)? {
        return None;
    }
    let knot_start = control_end.checked_add(1)?;
    let knot_end = knot_start.checked_add(knot_count)?;
    let mut previous = None;
    for field in fields.get(knot_start..knot_end)? {
        let value = parse_f64(field).filter(|value| value.is_finite())?;
        if previous.is_some_and(|previous| previous > value) {
            return None;
        }
        previous = Some(value);
    }
    let sample_count = parse_usize(fields.get(knot_end)?)?;
    let end = knot_end
        .checked_add(1)?
        .checked_add(sample_count.checked_mul(7)?)?;
    let sample_fields = fields.get(knot_end + 1..end)?;
    for sample in sample_fields.chunks_exact(7) {
        parse_u64(sample[0])?;
        for field in &sample[1..] {
            parse_f64(field).filter(|value| value.is_finite())?;
        }
    }
    Some(end)
}

fn parse_circle(fields: &[&[u8]], entity: EntityHeader) -> Result<SemanticEntity, String> {
    require_fields(fields, 9, "CIR")?;
    Ok(SemanticEntity::Circle(CircleEntity {
        graphic: parse_graphic_header(fields, entity)?,
        center_id: required_u64(fields, 7, "center point")?,
        circumference_id: required_u64(fields, 8, "circumference point")?,
        center: None,
        circumference: None,
    }))
}

fn parse_graphic_header(fields: &[&[u8]], entity: EntityHeader) -> Result<GraphicHeader, String> {
    let property_value = required_u64(fields, 6, "property pointer")?;
    Ok(GraphicHeader {
        entity,
        display_values: [
            required_i64(fields, 2, "display field 0")?,
            required_i64(fields, 3, "display field 1")?,
            required_i64(fields, 4, "display field 2")?,
            required_i64(fields, 5, "display field 3")?,
        ],
        property_id: (property_value != 0).then_some(property_value),
    })
}

fn build_entity_index(
    entities: &[SemanticEntity],
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) -> BTreeMap<EntityId, usize> {
    let mut entity_index = BTreeMap::new();
    for (index, entity) in entities.iter().enumerate() {
        if let Some(first_index) = entity_index.insert(entity.id(), index) {
            entity_index.insert(entity.id(), first_index);
            let record = &raw.records[entity.raw_record_index()];
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Error,
                code: "MI_DUPLICATE_ENTITY_ID",
                message: format!(
                    "entity ID {} duplicates source entity index {first_index}",
                    entity.id()
                ),
                span: record.payload_span,
                action: Some("repair entity numbering before relying on pointer resolution"),
            });
        }
    }
    entity_index
}

fn bind_part_structure(
    parts: &mut [Part],
    entities: &mut [SemanticEntity],
    entity_index: &BTreeMap<EntityId, usize>,
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) -> Vec<usize> {
    let assembly_entity_indices = entities
        .iter()
        .enumerate()
        .filter_map(|(index, entity)| {
            matches!(entity, SemanticEntity::Assembly(_)).then_some(index)
        })
        .collect::<Vec<_>>();
    let mut bound_parts = BTreeSet::new();
    for (ordinal, entity_index_value) in assembly_entity_indices.iter().copied().enumerate() {
        let SemanticEntity::Assembly(assembly) = &entities[entity_index_value] else {
            unreachable!("assembly indexes were filtered above")
        };
        let matching_part = assembly.part_name.as_ref().and_then(|name| {
            parts
                .iter()
                .find(|part| !bound_parts.contains(&part.index) && part.name.bytes == name.bytes)
                .map(|part| part.index)
        });
        let fallback_part = parts
            .get(ordinal)
            .filter(|part| !bound_parts.contains(&part.index))
            .map(|part| part.index);
        let Some(part_index) = matching_part.or(fallback_part) else {
            let record = &raw.records[assembly.entity.raw_record_index];
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Warning,
                code: "MI_UNBOUND_ASSEMBLY",
                message: format!(
                    "ASSE entity {} has no matching #~6 part definition",
                    assembly.entity.id
                ),
                span: record.payload_span,
                action: Some("inspect ASSE and #~6 names and ordering"),
            });
            continue;
        };
        if matching_part.is_none() {
            let record = &raw.records[assembly.entity.raw_record_index];
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Warning,
                code: "MI_ASSEMBLY_PART_NAME_MISMATCH",
                message: format!(
                    "ASSE entity {} was paired with part {part_index} by source order because names differ",
                    assembly.entity.id
                ),
                span: record.payload_span,
                action: Some("inspect version-specific ASSE name fields"),
            });
        }
        bound_parts.insert(part_index);
        parts[part_index].assembly_id = Some(assembly.entity.id);
        let SemanticEntity::Assembly(assembly) = &mut entities[entity_index_value] else {
            unreachable!("assembly indexes were filtered above")
        };
        assembly.definition_part_index = Some(part_index);
    }

    let mut assembly_parts = BTreeMap::new();
    for index in &assembly_entity_indices {
        let SemanticEntity::Assembly(assembly) = &entities[*index] else {
            continue;
        };
        if let Some(part_index) = assembly.definition_part_index {
            assembly_parts
                .entry(assembly.entity.id)
                .or_insert(part_index);
        }
    }
    let sheet_property_ids = entities
        .iter()
        .filter_map(|entity| match entity {
            SemanticEntity::Property(property)
                if property.mi_type == "ASSP"
                    && property
                        .values
                        .iter()
                        .any(|value| trim_ascii(value) == b"DOCU_SHEET") =>
            {
                Some(property.entity.id)
            }
            _ => None,
        })
        .collect::<BTreeSet<_>>();

    let mut edges = Vec::new();
    let mut sheet_part_indices = Vec::new();
    for entity_index_value in assembly_entity_indices {
        let SemanticEntity::Assembly(assembly) = &mut entities[entity_index_value] else {
            unreachable!("assembly indexes were filtered above")
        };
        let parent_part_index = assembly.definition_part_index;
        for instance in &mut assembly.instances {
            instance.is_sheet = instance
                .member_ids
                .iter()
                .any(|id| sheet_property_ids.contains(id));
            let target_part_index = assembly_parts.get(&instance.assembly_id).copied();
            instance.target_part_index = target_part_index;
            match (parent_part_index, target_part_index) {
                (Some(parent), Some(child)) => {
                    edges.push((parent, child));
                    if instance.is_sheet {
                        sheet_part_indices.push(child);
                    }
                }
                (_, None) => {
                    let record = &raw.records[assembly.entity.raw_record_index];
                    let (code, message) = if entity_index.contains_key(&instance.assembly_id) {
                        (
                            "MI_REFERENCE_TYPE_MISMATCH",
                            format!(
                                "ASSE entity {} child pointer {} does not reference a bound ASSE entity",
                                assembly.entity.id, instance.assembly_id
                            ),
                        )
                    } else {
                        (
                            "MI_DANGLING_ASSEMBLY_REFERENCE",
                            format!(
                                "ASSE entity {} child assembly {} does not exist",
                                assembly.entity.id, instance.assembly_id
                            ),
                        )
                    };
                    diagnostics.push(Diagnostic {
                        severity: DiagnosticSeverity::Warning,
                        code,
                        message,
                        span: record.payload_span,
                        action: Some("inspect the child ASSE pointer and #~5 part table"),
                    });
                }
                (None, Some(_)) => {}
            }
        }
    }
    for (parent, child) in edges {
        parts[parent].child_part_indices.push(child);
        if !parts[child].parent_part_indices.contains(&parent) {
            parts[child].parent_part_indices.push(parent);
        }
    }
    sheet_part_indices
}

fn resolve_references(
    entities: &mut [SemanticEntity],
    entity_index: &BTreeMap<EntityId, usize>,
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let points = entity_index
        .iter()
        .filter_map(|(id, index)| match &entities[*index] {
            SemanticEntity::Point(point) => Some((*id, point.location.clone())),
            _ => None,
        })
        .collect::<BTreeMap<_, _>>();
    let property_ids = entity_index
        .iter()
        .filter_map(|(id, index)| {
            matches!(entities[*index], SemanticEntity::Property(_)).then_some(*id)
        })
        .collect::<BTreeSet<_>>();

    for entity in entities {
        match entity {
            SemanticEntity::Line(line) => {
                line.start = resolve_point(
                    line.graphic.entity.id,
                    "start",
                    line.start_id,
                    &points,
                    entity_index,
                    raw,
                    line.graphic.entity.raw_record_index,
                    diagnostics,
                );
                line.end = resolve_point(
                    line.graphic.entity.id,
                    "end",
                    line.end_id,
                    &points,
                    entity_index,
                    raw,
                    line.graphic.entity.raw_record_index,
                    diagnostics,
                );
                validate_property(&line.graphic, &property_ids, entity_index, raw, diagnostics);
            }
            SemanticEntity::Arc(arc) => {
                arc.center = resolve_point(
                    arc.graphic.entity.id,
                    "center",
                    arc.center_id,
                    &points,
                    entity_index,
                    raw,
                    arc.graphic.entity.raw_record_index,
                    diagnostics,
                );
                arc.start = resolve_point(
                    arc.graphic.entity.id,
                    "start",
                    arc.start_id,
                    &points,
                    entity_index,
                    raw,
                    arc.graphic.entity.raw_record_index,
                    diagnostics,
                );
                arc.end = resolve_point(
                    arc.graphic.entity.id,
                    "end",
                    arc.end_id,
                    &points,
                    entity_index,
                    raw,
                    arc.graphic.entity.raw_record_index,
                    diagnostics,
                );
                validate_property(&arc.graphic, &property_ids, entity_index, raw, diagnostics);
            }
            SemanticEntity::Fillet(fillet) => {
                fillet.center = resolve_point(
                    fillet.graphic.entity.id,
                    "center",
                    fillet.center_id,
                    &points,
                    entity_index,
                    raw,
                    fillet.graphic.entity.raw_record_index,
                    diagnostics,
                );
                fillet.start = resolve_point(
                    fillet.graphic.entity.id,
                    "start",
                    fillet.start_id,
                    &points,
                    entity_index,
                    raw,
                    fillet.graphic.entity.raw_record_index,
                    diagnostics,
                );
                fillet.end = resolve_point(
                    fillet.graphic.entity.id,
                    "end",
                    fillet.end_id,
                    &points,
                    entity_index,
                    raw,
                    fillet.graphic.entity.raw_record_index,
                    diagnostics,
                );
                validate_property(
                    &fillet.graphic,
                    &property_ids,
                    entity_index,
                    raw,
                    diagnostics,
                );
            }
            SemanticEntity::BSpline(spline) => {
                spline.start = resolve_point(
                    spline.entity.id,
                    "start",
                    spline.start_id,
                    &points,
                    entity_index,
                    raw,
                    spline.entity.raw_record_index,
                    diagnostics,
                );
                spline.end = resolve_point(
                    spline.entity.id,
                    "end",
                    spline.end_id,
                    &points,
                    entity_index,
                    raw,
                    spline.entity.raw_record_index,
                    diagnostics,
                );
                spline.control_points = spline
                    .control_point_ids
                    .iter()
                    .map(|point_id| {
                        resolve_point(
                            spline.entity.id,
                            "control",
                            *point_id,
                            &points,
                            entity_index,
                            raw,
                            spline.entity.raw_record_index,
                            diagnostics,
                        )
                    })
                    .collect();
                for sample in &mut spline.samples {
                    sample.point = resolve_point(
                        spline.entity.id,
                        "sample",
                        sample.point_id,
                        &points,
                        entity_index,
                        raw,
                        spline.entity.raw_record_index,
                        diagnostics,
                    );
                }
                if let Some(graphic) = &spline.graphic {
                    validate_property(graphic, &property_ids, entity_index, raw, diagnostics);
                }
            }
            SemanticEntity::Circle(circle) => {
                circle.center = resolve_point(
                    circle.graphic.entity.id,
                    "center",
                    circle.center_id,
                    &points,
                    entity_index,
                    raw,
                    circle.graphic.entity.raw_record_index,
                    diagnostics,
                );
                circle.circumference = resolve_point(
                    circle.graphic.entity.id,
                    "circumference",
                    circle.circumference_id,
                    &points,
                    entity_index,
                    raw,
                    circle.graphic.entity.raw_record_index,
                    diagnostics,
                );
                validate_property(
                    &circle.graphic,
                    &property_ids,
                    entity_index,
                    raw,
                    diagnostics,
                );
            }
            SemanticEntity::Text(text) => {
                validate_property(&text.graphic, &property_ids, entity_index, raw, diagnostics);
            }
            SemanticEntity::Assembly(assembly) => {
                for property_id in &assembly.property_ids {
                    validate_property_pointer(
                        assembly.entity.id,
                        *property_id,
                        assembly.entity.raw_record_index,
                        &property_ids,
                        entity_index,
                        raw,
                        diagnostics,
                    );
                }
            }
            SemanticEntity::Point(_)
            | SemanticEntity::Dimension(_)
            | SemanticEntity::DimensionTolerance(_)
            | SemanticEntity::Leader(_)
            | SemanticEntity::Hatch(_)
            | SemanticEntity::Symbol(_)
            | SemanticEntity::Property(_)
            | SemanticEntity::Unsupported(_) => {}
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn resolve_point(
    owner_id: EntityId,
    role: &str,
    point_id: EntityId,
    points: &BTreeMap<EntityId, Point2>,
    entity_index: &BTreeMap<EntityId, usize>,
    raw: &RawDocument,
    raw_record_index: usize,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<Point2> {
    if let Some(point) = points.get(&point_id) {
        return Some(point.clone());
    }
    let record = &raw.records[raw_record_index];
    let (code, message) = if entity_index.contains_key(&point_id) {
        (
            "MI_REFERENCE_TYPE_MISMATCH",
            format!("entity {owner_id} {role} pointer {point_id} does not reference a P entity"),
        )
    } else {
        (
            "MI_DANGLING_POINT_REFERENCE",
            format!("entity {owner_id} {role} point {point_id} does not exist"),
        )
    };
    diagnostics.push(Diagnostic {
        severity: DiagnosticSeverity::Warning,
        code,
        message,
        span: record.payload_span,
        action: Some("inspect the referenced entity ID and section #~61"),
    });
    None
}

fn validate_property(
    graphic: &GraphicHeader,
    property_ids: &BTreeSet<EntityId>,
    entity_index: &BTreeMap<EntityId, usize>,
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(property_id) = graphic.property_id else {
        return;
    };
    validate_property_pointer(
        graphic.entity.id,
        property_id,
        graphic.entity.raw_record_index,
        property_ids,
        entity_index,
        raw,
        diagnostics,
    );
}

#[allow(clippy::too_many_arguments)]
fn validate_property_pointer(
    owner_id: EntityId,
    property_id: EntityId,
    raw_record_index: usize,
    property_ids: &BTreeSet<EntityId>,
    entity_index: &BTreeMap<EntityId, usize>,
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if property_ids.contains(&property_id) {
        return;
    }
    let record = &raw.records[raw_record_index];
    let (code, message) = if entity_index.contains_key(&property_id) {
        (
            "MI_REFERENCE_TYPE_MISMATCH",
            format!(
                "entity {} property pointer {property_id} does not reference a property entity",
                owner_id
            ),
        )
    } else {
        (
            "MI_DANGLING_PROPERTY_REFERENCE",
            format!("entity {owner_id} property {property_id} does not exist"),
        )
    };
    diagnostics.push(Diagnostic {
        severity: DiagnosticSeverity::Warning,
        code,
        message,
        span: record.payload_span,
        action: Some("inspect the property pointer and section #~41/#~42"),
    });
}

fn populate_parts(parts: &mut [Part], entities: &[SemanticEntity]) {
    for entity in entities {
        let Some(part_index) = entity.part_index() else {
            continue;
        };
        let Some(part) = parts.get_mut(part_index) else {
            continue;
        };
        part.source_entity_ids.push(entity.id());
        match entity {
            SemanticEntity::Point(_) => part.point_ids.push(entity.id()),
            SemanticEntity::Line(_)
            | SemanticEntity::Arc(_)
            | SemanticEntity::Fillet(_)
            | SemanticEntity::BSpline(_)
            | SemanticEntity::Circle(_)
            | SemanticEntity::Text(_) => {
                part.graphic_entity_ids.push(entity.id());
            }
            SemanticEntity::Dimension(_)
            | SemanticEntity::DimensionTolerance(_)
            | SemanticEntity::Leader(_)
            | SemanticEntity::Hatch(_)
            | SemanticEntity::Symbol(_) => part.annotation_entity_ids.push(entity.id()),
            SemanticEntity::Unsupported(_) => part.unsupported_entity_ids.push(entity.id()),
            SemanticEntity::Property(_) | SemanticEntity::Assembly(_) => {}
        }
    }
}

fn validate_toc_last(
    toc_last: Option<EntityId>,
    entities: &[SemanticEntity],
    raw: &RawDocument,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(toc_last) = toc_last else {
        return;
    };
    let actual_last = entities.iter().map(SemanticEntity::id).max();
    if actual_last == Some(toc_last) {
        return;
    }
    let span = raw
        .sections
        .iter()
        .find(|section| section.number == 2)
        .map_or(SourceSpan::new(0, 0, 1, 1), |section| section.body_span);
    diagnostics.push(Diagnostic {
        severity: DiagnosticSeverity::Warning,
        code: "MI_TOC_LAST_MISMATCH",
        message: format!(
            "table-of-contents LAST is {toc_last}, but the largest parsed entity ID is {}",
            actual_last.map_or_else(|| "none".to_owned(), |value| value.to_string())
        ),
        span,
        action: Some("inspect entity numbering and the LAST entry in section #~2"),
    });
}

fn parse_extents(fields: &[&[u8]]) -> Option<Bounds2> {
    Some(Bounds2 {
        min: Point2::new(finite_f64_field(fields, 13)?, finite_f64_field(fields, 15)?),
        max: Point2::new(finite_f64_field(fields, 14)?, finite_f64_field(fields, 16)?),
    })
}

fn parse_transform(fields: &[&[u8]]) -> Option<[f64; 16]> {
    let mut result = [0.0; 16];
    for (destination, index) in result.iter_mut().zip(29..45) {
        *destination = finite_f64_field(fields, index)?;
    }
    Some(result)
}

fn decoded_text_field(
    data: &[u8],
    fields: &[&[u8]],
    index: usize,
    start_line: usize,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
    context: &str,
) -> Option<TextValue> {
    fields.get(index).map(|field| {
        decode_text_value(
            data,
            field,
            start_line + index,
            encoding,
            diagnostics,
            context,
        )
    })
}

fn decode_text_value(
    data: &[u8],
    bytes: &[u8],
    line: usize,
    encoding: &EncodingInfo,
    diagnostics: &mut Vec<Diagnostic>,
    context: &str,
) -> TextValue {
    let text = if let Some(text_encoding) = encoding.encoding {
        match text_encoding.decode(bytes) {
            Ok(text) => Some(text),
            Err(error) => {
                let field_span = field_source_span(data, bytes, line);
                diagnostics.push(Diagnostic {
                    severity: DiagnosticSeverity::Warning,
                    code: "MI_TEXT_DECODE_ERROR",
                    message: format!(
                        "{context} is not valid {} at field byte {}",
                        text_encoding.name(),
                        error.offset
                    ),
                    span: SourceSpan::new(
                        field_span.offset + error.offset,
                        error
                            .length
                            .min(bytes.len().saturating_sub(error.offset))
                            .max(1),
                        line,
                        line,
                    ),
                    action: Some("inspect the raw bytes or pass the correct encoding override"),
                });
                None
            }
        }
    } else if bytes.is_ascii() {
        Some(String::from_utf8(bytes.to_vec()).expect("ASCII is valid UTF-8"))
    } else {
        None
    };
    TextValue {
        bytes: bytes.to_vec(),
        text,
        encoding: encoding.encoding,
    }
}

fn field_source_span(data: &[u8], field: &[u8], line: usize) -> SourceSpan {
    let data_start = data.as_ptr() as usize;
    let field_start = field.as_ptr() as usize;
    let offset = field_start
        .checked_sub(data_start)
        .filter(|offset| *offset <= data.len())
        .unwrap_or_default();
    SourceSpan::new(offset, field.len(), line, line)
}

fn ascii_field(fields: &[&[u8]], index: usize) -> Option<String> {
    std::str::from_utf8(trim_ascii(fields.get(index)?))
        .ok()
        .map(str::to_owned)
}

fn finite_f64_field(fields: &[&[u8]], index: usize) -> Option<f64> {
    parse_f64(fields.get(index)?).filter(|value| value.is_finite())
}

fn invalid_global_field(section: &RawSection, message: &str) -> Diagnostic {
    Diagnostic {
        severity: DiagnosticSeverity::Warning,
        code: "MI_INVALID_GLOBAL_FIELD",
        message: message.to_owned(),
        span: section.body_span,
        action: Some("inspect the MI version and global section field layout"),
    }
}

fn require_fields(fields: &[&[u8]], expected: usize, mi_type: &str) -> Result<(), String> {
    if fields.len() < expected {
        return Err(format!(
            "{mi_type} requires at least {expected} fields, found {}",
            fields.len()
        ));
    }
    Ok(())
}

fn required_u64(fields: &[&[u8]], index: usize, name: &str) -> Result<u64, String> {
    fields
        .get(index)
        .and_then(|field| parse_u64(field))
        .ok_or_else(|| format!("{name} at field {index} is not an unsigned integer"))
}

fn required_usize(fields: &[&[u8]], index: usize, name: &str) -> Result<usize, String> {
    fields
        .get(index)
        .and_then(|field| parse_usize(field))
        .ok_or_else(|| format!("{name} at field {index} is not a non-negative field count"))
}

fn required_i64(fields: &[&[u8]], index: usize, name: &str) -> Result<i64, String> {
    fields
        .get(index)
        .and_then(|field| parse_i64(field))
        .ok_or_else(|| format!("{name} at field {index} is not an integer"))
}

fn required_f64(fields: &[&[u8]], index: usize, name: &str) -> Result<f64, String> {
    fields
        .get(index)
        .and_then(|field| parse_f64(field))
        .filter(|value| value.is_finite())
        .ok_or_else(|| format!("{name} at field {index} is not a finite number"))
}

fn parse_f64_array<const N: usize>(
    fields: &[&[u8]],
    start: usize,
    name: &str,
) -> Result<[f64; N], String> {
    let mut result = [0.0; N];
    for (offset, value) in result.iter_mut().enumerate() {
        *value = required_f64(fields, start + offset, name)?;
    }
    Ok(result)
}

fn parse_u64(value: &[u8]) -> Option<u64> {
    std::str::from_utf8(trim_ascii(value)).ok()?.parse().ok()
}

fn parse_usize(value: &[u8]) -> Option<usize> {
    std::str::from_utf8(trim_ascii(value)).ok()?.parse().ok()
}

fn parse_i64(value: &[u8]) -> Option<i64> {
    std::str::from_utf8(trim_ascii(value)).ok()?.parse().ok()
}

fn parse_f64(value: &[u8]) -> Option<f64> {
    std::str::from_utf8(trim_ascii(value)).ok()?.parse().ok()
}

fn trim_ascii(mut value: &[u8]) -> &[u8] {
    while value.first().is_some_and(u8::is_ascii_whitespace) {
        value = &value[1..];
    }
    while value.last().is_some_and(u8::is_ascii_whitespace) {
        value = &value[..value.len() - 1];
    }
    value
}

fn split_lines(data: &[u8]) -> Vec<&[u8]> {
    let mut result = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let start = offset;
        while offset < data.len() && !matches!(data[offset], b'\r' | b'\n') {
            offset += 1;
        }
        result.push(&data[start..offset]);
        if offset < data.len() {
            if data[offset] == b'\r' && offset + 1 < data.len() && data[offset + 1] == b'\n' {
                offset += 2;
            } else {
                offset += 1;
            }
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_all_supported_line_endings_without_a_trailing_empty_field() {
        assert_eq!(
            split_lines(b"P\r\n1\n2\r3\r\n"),
            vec![b"P".as_slice(), b"1", b"2", b"3"]
        );
    }

    #[test]
    fn rejects_non_finite_coordinates() {
        let fields = [b"P".as_slice(), b"1", b"NaN", b"0"];
        let error = parse_point(
            &fields,
            EntityHeader {
                id: 1,
                raw_record_index: 0,
                part_index: None,
            },
        )
        .unwrap_err();
        assert!(error.contains("finite number"));
    }

    #[test]
    fn locates_assembly_names_after_all_property_pointers() {
        let fields = [
            b"ASSE".as_slice(),
            b"1",
            b"2",
            b"10",
            b"11",
            b"assembly name",
        ];

        assert_eq!(assembly_name_index(&fields), Some(5));
    }
}
