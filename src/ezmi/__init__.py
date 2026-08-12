"""Lossless MI reader powered by Rust."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from . import _core
from ._core import InvalidMiError, MiError, MiLimitError, UnsupportedMiError
from .diagnostics import Diagnostic, DiagnosticSeverity, SourceSpan
from .document import Document, Drawing, EncodingInfo, GlobalInfo, Part, read, readfile
from .entities import (
    AddressableEntity,
    Annotation,
    Arc,
    Assembly,
    AssemblyInstance,
    Bounds2,
    BSpline,
    BSplineSample,
    Circle,
    Dimension,
    DimensionTolerance,
    Fillet,
    Graphic,
    GraphicEntity,
    Hatch,
    Leader,
    Line,
    MiEntity,
    Point,
    Property,
    StructuredEntity,
    Symbol,
    Text,
    TextValue,
    UnsupportedEntity,
    Vec2,
)
from .raw import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_LINE_SIZE_BYTES,
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_RECORD_SIZE_BYTES,
    DEFAULT_MAX_RECORDS,
    DEFAULT_MAX_SECTIONS,
    BytesSource,
    CompressionKind,
    FileTerminationKind,
    FormatKind,
    LineEndingKind,
    LineKind,
    MiFormatInfo,
    MiSource,
    NewlineSummary,
    PathSource,
    RawLine,
    RawRecord,
    RawScan,
    RawSection,
    RecordTerminationKind,
    ScanLimits,
    detect_format,
    scan,
    scan_records,
)

try:
    __version__ = version("ezmi")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = _core.core_version()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ezmi command-line interface."""

    from .__main__ import main as cli_main

    return cli_main(argv)


__all__ = [
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_LINE_SIZE_BYTES",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_MAX_RECORD_SIZE_BYTES",
    "DEFAULT_MAX_SECTIONS",
    "AddressableEntity",
    "Annotation",
    "Arc",
    "Assembly",
    "AssemblyInstance",
    "BSpline",
    "BSplineSample",
    "Bounds2",
    "BytesSource",
    "Circle",
    "CompressionKind",
    "Diagnostic",
    "DiagnosticSeverity",
    "Dimension",
    "DimensionTolerance",
    "Document",
    "Drawing",
    "EncodingInfo",
    "FileTerminationKind",
    "Fillet",
    "FormatKind",
    "GlobalInfo",
    "Graphic",
    "GraphicEntity",
    "Hatch",
    "InvalidMiError",
    "Leader",
    "Line",
    "LineEndingKind",
    "LineKind",
    "MiEntity",
    "MiError",
    "MiFormatInfo",
    "MiLimitError",
    "MiSource",
    "NewlineSummary",
    "Part",
    "PathSource",
    "Point",
    "Property",
    "RawLine",
    "RawRecord",
    "RawScan",
    "RawSection",
    "RecordTerminationKind",
    "ScanLimits",
    "SourceSpan",
    "StructuredEntity",
    "Symbol",
    "Text",
    "TextValue",
    "UnsupportedEntity",
    "UnsupportedMiError",
    "Vec2",
    "__version__",
    "detect_format",
    "main",
    "read",
    "readfile",
    "scan",
    "scan_records",
]
