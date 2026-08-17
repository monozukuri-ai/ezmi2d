//! Rust core for byte-preserving MI reading and verified legacy geometry/text decoding.

mod compression;
mod encoding;
mod error;
mod model;
mod options;
mod raw;
mod scanner;
mod semantic;

pub use compression::{decode_input, DecodedInput};
pub use encoding::{EncodingSource, TextDecodeError, TextEncoding};
pub use error::MiError;
pub use model::{
    ArcEntity, AssemblyEntity, AssemblyInstance, BSplineEntity, BSplineSample, Bounds2,
    CircleEntity, ContourEntity, DimensionEntity, DimensionTextAttributeProperty,
    DimensionToleranceEntity, EncodingInfo, EntityHeader, EntityId, GlobalInfo, GraphicHeader,
    HatchAssociationEntity, HatchEntity, HatchPatternLine, HatchPatternProperty, LeaderEntity,
    LeaderPoint, LineEntity, Part, PartStatusProperty, Point2, PointEntity, PropertyEntity,
    SemanticDocument, SemanticEntity, StructuredEntity, SymbolEntity, TextEntity, TextValue,
    UnsupportedEntity,
};
pub use options::{
    ScanOptions, DEFAULT_MAX_COMPRESSION_RATIO, DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES, DEFAULT_MAX_LINES, DEFAULT_MAX_LINE_SIZE_BYTES,
    DEFAULT_MAX_RECORDS, DEFAULT_MAX_RECORD_SIZE_BYTES, DEFAULT_MAX_SECTIONS,
};
pub use raw::{
    CompressionKind, Diagnostic, DiagnosticSeverity, FileTermination, LineEnding, MiFormatInfo,
    MiFormatKind, NewlineSummary, RawDocument, RawLine, RawLineKind, RawRecord, RawSection,
    RecordTermination, SourceSpan,
};
pub use scanner::{detect_format, scan, scan_input, ScannedInput};
pub use semantic::{read, read_input_with_encoding, read_with_encoding, SemanticInput};

pub const fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
