use std::borrow::Cow;

use crate::compression::{decode_input, detect_compression};
use crate::error::MiError;
use crate::options::ScanOptions;
use crate::raw::{
    Diagnostic, DiagnosticSeverity, FileTermination, LineEnding, MiFormatInfo, MiFormatKind,
    NewlineSummary, RawDocument, RawLine, RawLineKind, RawRecord, RawSection, RecordTermination,
    SourceSpan,
};

const FORMAT_PROBE_BYTES: usize = 64 * 1024;
const UTF8_BOM: &[u8] = b"\xef\xbb\xbf";

struct SectionBuilder {
    index: usize,
    number: u32,
    marker_span: SourceSpan,
    body_start: usize,
    body_start_line: usize,
    record_start: usize,
    record_start_line: usize,
    first_record: usize,
}

/// A scanned document together with the logical MI bytes addressed by its spans.
#[derive(Debug)]
pub struct ScannedInput<'a> {
    pub source: Cow<'a, [u8]>,
    pub document: RawDocument,
}

/// Detect text MI or a conservative compressed-stream candidate.
pub fn detect_format(data: &[u8]) -> Result<MiFormatInfo, MiError> {
    let utf8_bom = data.starts_with(UTF8_BOM);
    let probe = &data[..data.len().min(FORMAT_PROBE_BYTES)];
    let text_start = usize::from(utf8_bom) * UTF8_BOM.len();

    if let Some(first_line) = first_nonempty_line(&probe[text_start..]) {
        if let Some(first_section) = parse_section_marker(first_line) {
            return Ok(MiFormatInfo {
                kind: MiFormatKind::Text,
                compression: None,
                first_section: Some(first_section),
                utf8_bom,
            });
        }
    }

    if let Some(compression) = detect_compression(data) {
        return Ok(MiFormatInfo {
            kind: MiFormatKind::CompressedCandidate,
            compression: Some(compression),
            first_section: None,
            utf8_bom: false,
        });
    }

    Err(MiError::InvalidFormat)
}

/// Scan an MI stream without decoding positional entity fields.
pub fn scan(data: &[u8], options: ScanOptions) -> Result<RawDocument, MiError> {
    Ok(scan_input(data, options)?.document)
}

/// Prepare and scan an MI stream while retaining its logical source bytes.
pub fn scan_input(data: &[u8], options: ScanOptions) -> Result<ScannedInput<'_>, MiError> {
    let decoded = decode_input(data, options)?;
    let mut document = scan_text(decoded.bytes.as_ref(), options)?;
    document.format.compression = decoded.compression;
    document.container_size = decoded.container_size;
    Ok(ScannedInput {
        source: decoded.bytes,
        document,
    })
}

fn scan_text(data: &[u8], options: ScanOptions) -> Result<RawDocument, MiError> {
    check_limit(
        "decompressed bytes",
        data.len(),
        options.max_decompressed_size,
    )?;
    let format = detect_format(data)?;

    let (lines, newlines) = scan_lines(data, options)?;
    let mut diagnostics = Vec::new();
    if newlines.distinct_terminated_kinds() > 1 {
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_MIXED_LINE_ENDINGS",
            message: "input uses more than one physical line-ending style".to_owned(),
            span: whole_source_span(data, &lines),
            action: Some("preserve original line endings when rewriting the file"),
        });
    }

    let first_section_line = lines
        .iter()
        .find(|line| matches!(line.kind, RawLineKind::SectionMarker(_)));
    let first_section_offset = first_section_line.map_or(0, |line| line.span.offset);
    let first_section_number = first_section_line.map_or(1, |line| line.number);
    let preamble_end_line = if first_section_offset == 0 {
        1
    } else {
        first_section_number.saturating_sub(1).max(1)
    };
    let preamble_span = SourceSpan::new(0, first_section_offset, 1, preamble_end_line);

    let mut sections = Vec::new();
    let mut records = Vec::new();
    let mut current: Option<SectionBuilder> = None;
    let mut file_terminator_span = None;
    let mut trailing_bytes = 0usize;

    for line in &lines {
        if file_terminator_span.is_some() {
            continue;
        }

        match line.kind {
            RawLineKind::SectionMarker(number) => {
                if let Some(builder) = current.take() {
                    finalize_section(
                        data,
                        builder,
                        line.span.offset,
                        line.number,
                        RecordTermination::SectionBoundary,
                        &mut sections,
                        &mut records,
                        &mut diagnostics,
                        options,
                    )?;
                }

                check_limit("section count", sections.len() + 1, options.max_sections)?;
                current = Some(SectionBuilder {
                    index: sections.len(),
                    number,
                    marker_span: line.span,
                    body_start: line.span.end_offset(),
                    body_start_line: line.number + 1,
                    record_start: line.span.end_offset(),
                    record_start_line: line.number + 1,
                    first_record: records.len(),
                });
            }
            RawLineKind::EntityTerminator => {
                if let Some(builder) = current.as_mut() {
                    append_entity_record(data, builder, line, &mut records, options)?;
                } else {
                    diagnostics.push(Diagnostic {
                        severity: DiagnosticSeverity::Warning,
                        code: "MI_ENTITY_TERMINATOR_OUTSIDE_SECTION",
                        message: "entity terminator appears before the first section".to_owned(),
                        span: line.span,
                        action: Some("check the section marker preceding this terminator"),
                    });
                }
            }
            RawLineKind::FileTerminator => {
                if let Some(builder) = current.take() {
                    finalize_section(
                        data,
                        builder,
                        line.span.offset,
                        line.number,
                        RecordTermination::FileBoundary,
                        &mut sections,
                        &mut records,
                        &mut diagnostics,
                        options,
                    )?;
                }
                file_terminator_span = Some(line.span);
                trailing_bytes = data.len().saturating_sub(line.span.end_offset());
                if trailing_bytes > 0 {
                    diagnostics.push(Diagnostic {
                        severity: DiagnosticSeverity::Warning,
                        code: "MI_TRAILING_DATA",
                        message: format!(
                            "{trailing_bytes} byte(s) follow the first ##~~ file terminator"
                        ),
                        span: SourceSpan::new(
                            line.span.end_offset(),
                            trailing_bytes,
                            line.number + 1,
                            lines.last().map_or(line.number + 1, |last| last.number),
                        ),
                        action: Some("inspect or remove data after the first file terminator"),
                    });
                }
            }
            RawLineKind::Blank | RawLineKind::Data => {}
        }
    }

    let (termination, end_offset) = if let Some(span) = file_terminator_span {
        (FileTermination::FileMarker, span.end_offset())
    } else {
        if let Some(builder) = current.take() {
            let eof_line = lines.last().map_or(1, |line| line.number);
            finalize_section(
                data,
                builder,
                data.len(),
                eof_line + 1,
                RecordTermination::PhysicalEof,
                &mut sections,
                &mut records,
                &mut diagnostics,
                options,
            )?;
        }
        let eof_line = lines.last().map_or(1, |line| line.number);
        diagnostics.push(Diagnostic {
            severity: DiagnosticSeverity::Warning,
            code: "MI_MISSING_FILE_TERMINATOR",
            message: "input reached physical EOF without a ##~~ file terminator".to_owned(),
            span: SourceSpan::new(data.len(), 0, eof_line, eof_line),
            action: Some("verify that the MI stream was not truncated"),
        });
        (FileTermination::PhysicalEof, data.len())
    };

    Ok(RawDocument {
        format,
        lines,
        sections,
        records,
        diagnostics,
        preamble_span,
        file_terminator_span,
        termination,
        end_offset,
        trailing_bytes,
        container_size: data.len(),
        source_size: data.len(),
        newlines,
    })
}

fn scan_lines(
    data: &[u8],
    options: ScanOptions,
) -> Result<(Vec<RawLine>, NewlineSummary), MiError> {
    let mut lines = Vec::new();
    let mut newlines = NewlineSummary::default();
    let mut offset = 0usize;

    while offset < data.len() {
        let content_start = offset;
        while offset < data.len() && data[offset] != b'\r' && data[offset] != b'\n' {
            offset += 1;
        }
        let content_end = offset;
        let ending = if offset == data.len() {
            newlines.unterminated += 1;
            LineEnding::None
        } else if data[offset] == b'\r' && offset + 1 < data.len() && data[offset + 1] == b'\n' {
            offset += 2;
            newlines.crlf += 1;
            LineEnding::Crlf
        } else if data[offset] == b'\r' {
            offset += 1;
            newlines.cr += 1;
            LineEnding::Cr
        } else {
            offset += 1;
            newlines.lf += 1;
            LineEnding::Lf
        };

        check_limit(
            "line size bytes",
            content_end - content_start,
            options.max_line_size,
        )?;
        check_limit("line count", lines.len() + 1, options.max_lines)?;

        let number = lines.len() + 1;
        let content_span =
            SourceSpan::new(content_start, content_end - content_start, number, number);
        let span = SourceSpan::new(content_start, offset - content_start, number, number);
        let content = &data[content_start..content_end];
        let classified = if number == 1 && content.starts_with(UTF8_BOM) {
            &content[UTF8_BOM.len()..]
        } else {
            content
        };
        lines.push(RawLine {
            index: lines.len(),
            number,
            span,
            content_span,
            ending,
            kind: classify_line(classified),
        });
    }

    Ok((lines, newlines))
}

#[allow(clippy::too_many_arguments)]
fn finalize_section(
    data: &[u8],
    builder: SectionBuilder,
    body_end: usize,
    boundary_line: usize,
    boundary: RecordTermination,
    sections: &mut Vec<RawSection>,
    records: &mut Vec<RawRecord>,
    diagnostics: &mut Vec<Diagnostic>,
    options: ScanOptions,
) -> Result<(), MiError> {
    if builder.record_start < body_end
        && contains_non_whitespace(&data[builder.record_start..body_end])
    {
        let end_line = boundary_line
            .saturating_sub(1)
            .max(builder.record_start_line);
        let span = SourceSpan::new(
            builder.record_start,
            body_end - builder.record_start,
            builder.record_start_line,
            end_line,
        );
        append_record(
            records,
            RawRecord {
                index: records.len(),
                section_index: builder.index,
                section_number: builder.number,
                span,
                payload_span: span,
                terminator_span: None,
                termination: boundary,
                record_type: None,
            },
            options,
        )?;

        if expects_entity_terminators(builder.number) {
            diagnostics.push(Diagnostic {
                severity: DiagnosticSeverity::Warning,
                code: "MI_UNTERMINATED_RECORD",
                message: format!(
                    "section #~{} contains data not terminated by |~",
                    builder.number
                ),
                span,
                action: Some("verify the record framing and source completeness"),
            });
        }
    }

    let end_line = boundary_line
        .saturating_sub(1)
        .max(builder.marker_span.start_line);
    let body_length = body_end.saturating_sub(builder.body_start);
    let (body_start_line, body_end_line) = if body_length == 0 {
        (builder.marker_span.end_line, builder.marker_span.end_line)
    } else {
        (builder.body_start_line, end_line)
    };
    let body_span = SourceSpan::new(
        builder.body_start,
        body_length,
        body_start_line,
        body_end_line,
    );
    sections.push(RawSection {
        index: builder.index,
        number: builder.number,
        span: SourceSpan::new(
            builder.marker_span.offset,
            body_end.saturating_sub(builder.marker_span.offset),
            builder.marker_span.start_line,
            end_line,
        ),
        marker_span: builder.marker_span,
        body_span,
        first_record: builder.first_record,
        record_count: records.len() - builder.first_record,
    });
    Ok(())
}

fn append_entity_record(
    data: &[u8],
    builder: &mut SectionBuilder,
    terminator: &RawLine,
    records: &mut Vec<RawRecord>,
    options: ScanOptions,
) -> Result<(), MiError> {
    let payload_length = terminator.span.offset.saturating_sub(builder.record_start);
    let span = SourceSpan::new(
        builder.record_start,
        terminator.span.end_offset() - builder.record_start,
        builder.record_start_line,
        terminator.number,
    );
    let payload_span = SourceSpan::new(
        builder.record_start,
        payload_length,
        builder.record_start_line,
        terminator
            .number
            .saturating_sub(1)
            .max(builder.record_start_line),
    );
    let record_type =
        first_ascii_record_type(&data[payload_span.offset..payload_span.end_offset()]);
    append_record(
        records,
        RawRecord {
            index: records.len(),
            section_index: builder.index,
            section_number: builder.number,
            span,
            payload_span,
            terminator_span: Some(terminator.span),
            termination: RecordTermination::EntityMarker,
            record_type,
        },
        options,
    )?;
    builder.record_start = terminator.span.end_offset();
    builder.record_start_line = terminator.number + 1;
    Ok(())
}

fn append_record(
    records: &mut Vec<RawRecord>,
    record: RawRecord,
    options: ScanOptions,
) -> Result<(), MiError> {
    check_limit(
        "record size bytes",
        record.span.length,
        options.max_record_size,
    )?;
    check_limit("record count", records.len() + 1, options.max_records)?;
    records.push(record);
    Ok(())
}

fn check_limit(resource: &'static str, actual: usize, limit: usize) -> Result<(), MiError> {
    if actual > limit {
        return Err(MiError::LimitExceeded {
            resource,
            actual,
            limit,
        });
    }
    Ok(())
}

fn classify_line(content: &[u8]) -> RawLineKind {
    let trimmed = trim_ascii_whitespace(content);
    if trimmed.is_empty() {
        RawLineKind::Blank
    } else if trimmed == b"|~" {
        RawLineKind::EntityTerminator
    } else if trimmed == b"##~~" {
        RawLineKind::FileTerminator
    } else if let Some(number) = parse_section_marker(trimmed) {
        RawLineKind::SectionMarker(number)
    } else {
        RawLineKind::Data
    }
}

fn first_nonempty_line(mut data: &[u8]) -> Option<&[u8]> {
    while !data.is_empty() {
        let content_end = data
            .iter()
            .position(|byte| matches!(byte, b'\r' | b'\n'))
            .unwrap_or(data.len());
        let line = trim_ascii_whitespace(&data[..content_end]);
        if !line.is_empty() {
            return Some(line);
        }
        if content_end == data.len() {
            break;
        }
        let mut next = content_end + 1;
        if data[content_end] == b'\r' && next < data.len() && data[next] == b'\n' {
            next += 1;
        }
        data = &data[next..];
    }
    None
}

fn parse_section_marker(content: &[u8]) -> Option<u32> {
    let digits = content.strip_prefix(b"#~")?;
    if digits.is_empty() || !digits.iter().all(u8::is_ascii_digit) {
        return None;
    }
    digits.iter().try_fold(0u32, |value, digit| {
        value.checked_mul(10)?.checked_add(u32::from(digit - b'0'))
    })
}

fn first_ascii_record_type(payload: &[u8]) -> Option<String> {
    let line = first_nonempty_line(payload)?;
    if line.is_empty()
        || !line
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
        || !line[0].is_ascii_alphabetic()
    {
        return None;
    }
    Some(String::from_utf8(line.to_vec()).expect("validated ASCII record type"))
}

fn trim_ascii_whitespace(mut data: &[u8]) -> &[u8] {
    while data.first().is_some_and(u8::is_ascii_whitespace) {
        data = &data[1..];
    }
    while data.last().is_some_and(u8::is_ascii_whitespace) {
        data = &data[..data.len() - 1];
    }
    data
}

fn contains_non_whitespace(data: &[u8]) -> bool {
    data.iter().any(|byte| !byte.is_ascii_whitespace())
}

fn expects_entity_terminators(section: u32) -> bool {
    matches!(section, 41 | 42 | 5 | 61 | 62 | 63 | 71 | 72 | 81 | 82)
}

fn whole_source_span(data: &[u8], lines: &[RawLine]) -> SourceSpan {
    SourceSpan::new(0, data.len(), 1, lines.last().map_or(1, |line| line.number))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::raw::CompressionKind;

    #[test]
    fn detects_text_after_bom_and_blank_lines() {
        let info = detect_format(b"\xef\xbb\xbf\r\n#~1\r\n##~~\r\n").unwrap();
        assert_eq!(info.kind, MiFormatKind::Text);
        assert_eq!(info.first_section, Some(1));
        assert!(info.utf8_bom);
    }

    #[test]
    fn detects_compression_candidates_without_claiming_bi() {
        for (candidate, compression, name) in [
            (&[0x78, 0x9c, 0x03, 0x00][..], CompressionKind::Zlib, "zlib"),
            (
                &[0x1f, 0x1e, 0x00, 0x00][..],
                CompressionKind::UnixPack,
                "unix_pack",
            ),
        ] {
            let info = detect_format(candidate).unwrap();
            assert_eq!(info.kind, MiFormatKind::CompressedCandidate);
            assert_eq!(info.compression, Some(compression));
            assert!(matches!(
                scan(candidate, ScanOptions::default()),
                Err(MiError::UnsupportedCompression { compression }) if compression == name
            ));
        }

        // unix compress(1) streams are decoded since 0.2.1; a stream whose
        // payload is not MI text is rejected as invalid instead.
        let candidate: &[u8] = &[0x1f, 0x9d, 0x90, 0x00];
        let info = detect_format(candidate).unwrap();
        assert_eq!(info.kind, MiFormatKind::CompressedCandidate);
        assert_eq!(info.compression, Some(CompressionKind::UnixCompress));
        assert!(matches!(
            scan(candidate, ScanOptions::default()),
            Err(MiError::InvalidCompressedStream { compression, .. }) if compression == "unix_compress"
        ));
    }

    #[test]
    fn preserves_mixed_line_endings_and_physical_eof() {
        let scan = scan(b"#~61\r\nP\n1\r0\n0\n|~", ScanOptions::default()).unwrap();
        assert_eq!(scan.termination, FileTermination::PhysicalEof);
        assert_eq!(scan.records.len(), 1);
        assert_eq!(scan.records[0].record_type.as_deref(), Some("P"));
        assert!(scan
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "MI_MIXED_LINE_ENDINGS"));
        assert!(scan
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "MI_MISSING_FILE_TERMINATOR"));
    }

    #[test]
    fn enforces_line_and_record_limits() {
        let options = ScanOptions {
            max_lines: 1,
            ..ScanOptions::default()
        };
        assert!(matches!(
            scan(b"#~61\nP\n|~\n##~~\n", options),
            Err(MiError::LimitExceeded {
                resource: "line count",
                ..
            })
        ));

        let options = ScanOptions {
            max_record_size: 2,
            ..ScanOptions::default()
        };
        assert!(matches!(
            scan(b"#~61\nP\n|~\n##~~\n", options),
            Err(MiError::LimitExceeded {
                resource: "record size bytes",
                ..
            })
        ));
    }
}
