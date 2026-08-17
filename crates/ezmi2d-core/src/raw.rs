/// Byte and line range within the logical, decompressed MI stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SourceSpan {
    pub offset: usize,
    pub length: usize,
    pub start_line: usize,
    pub end_line: usize,
}

impl SourceSpan {
    pub const fn new(offset: usize, length: usize, start_line: usize, end_line: usize) -> Self {
        Self {
            offset,
            length,
            start_line,
            end_line,
        }
    }

    pub const fn end_offset(self) -> usize {
        self.offset + self.length
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompressionKind {
    Zlib,
    Gzip,
    Zip,
    UnixCompress,
    UnixPack,
}

impl CompressionKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Zlib => "zlib",
            Self::Gzip => "gzip",
            Self::Zip => "zip",
            Self::UnixCompress => "unix_compress",
            Self::UnixPack => "unix_pack",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MiFormatKind {
    Text,
    CompressedCandidate,
}

impl MiFormatKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Text => "mi_text",
            Self::CompressedCandidate => "compressed_candidate",
        }
    }
}

/// Conservative format information from probing or a prepared logical stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MiFormatInfo {
    pub kind: MiFormatKind,
    pub compression: Option<CompressionKind>,
    pub first_section: Option<u32>,
    pub utf8_bom: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineEnding {
    Lf,
    Crlf,
    Cr,
    None,
}

impl LineEnding {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Lf => "lf",
            Self::Crlf => "crlf",
            Self::Cr => "cr",
            Self::None => "none",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RawLineKind {
    Blank,
    Data,
    SectionMarker(u32),
    EntityTerminator,
    FileTerminator,
}

impl RawLineKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Blank => "blank",
            Self::Data => "data",
            Self::SectionMarker(_) => "section_marker",
            Self::EntityTerminator => "entity_terminator",
            Self::FileTerminator => "file_terminator",
        }
    }

    pub const fn section_number(self) -> Option<u32> {
        match self {
            Self::SectionMarker(number) => Some(number),
            _ => None,
        }
    }
}

/// One physical source line, including its original line ending in `span`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawLine {
    pub index: usize,
    pub number: usize,
    pub span: SourceSpan,
    pub content_span: SourceSpan,
    pub ending: LineEnding,
    pub kind: RawLineKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordTermination {
    EntityMarker,
    SectionBoundary,
    FileBoundary,
    PhysicalEof,
}

impl RecordTermination {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::EntityMarker => "entity_marker",
            Self::SectionBoundary => "section_boundary",
            Self::FileBoundary => "file_boundary",
            Self::PhysicalEof => "physical_eof",
        }
    }
}

/// One `|~`-framed entity or one unframed section payload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawRecord {
    pub index: usize,
    pub section_index: usize,
    pub section_number: u32,
    pub span: SourceSpan,
    pub payload_span: SourceSpan,
    pub terminator_span: Option<SourceSpan>,
    pub termination: RecordTermination,
    pub record_type: Option<String>,
}

/// One `#~N` section and its byte-exact body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawSection {
    pub index: usize,
    pub number: u32,
    pub span: SourceSpan,
    pub marker_span: SourceSpan,
    pub body_span: SourceSpan,
    pub first_record: usize,
    pub record_count: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiagnosticSeverity {
    Info,
    Warning,
    Error,
}

impl DiagnosticSeverity {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Info => "info",
            Self::Warning => "warning",
            Self::Error => "error",
        }
    }
}

/// Stable, source-located observation that does not prevent lossless scanning.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnostic {
    pub severity: DiagnosticSeverity,
    pub code: &'static str,
    pub message: String,
    pub span: SourceSpan,
    pub action: Option<&'static str>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NewlineSummary {
    pub lf: usize,
    pub crlf: usize,
    pub cr: usize,
    pub unterminated: usize,
}

impl NewlineSummary {
    pub fn distinct_terminated_kinds(self) -> usize {
        usize::from(self.lf > 0) + usize::from(self.crlf > 0) + usize::from(self.cr > 0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileTermination {
    FileMarker,
    PhysicalEof,
}

impl FileTermination {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::FileMarker => "file_marker",
            Self::PhysicalEof => "physical_eof",
        }
    }
}

/// Complete result of one bounded, logical-byte-preserving scan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawDocument {
    pub format: MiFormatInfo,
    pub lines: Vec<RawLine>,
    pub sections: Vec<RawSection>,
    pub records: Vec<RawRecord>,
    pub diagnostics: Vec<Diagnostic>,
    pub preamble_span: SourceSpan,
    pub file_terminator_span: Option<SourceSpan>,
    pub termination: FileTermination,
    pub end_offset: usize,
    pub trailing_bytes: usize,
    /// Size of the original container passed by the caller.
    pub container_size: usize,
    /// Size of the logical MI byte stream addressed by all spans.
    pub source_size: usize,
    pub newlines: NewlineSummary,
}
