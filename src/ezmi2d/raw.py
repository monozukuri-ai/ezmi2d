"""Low-level, bounded, byte-preserving MI stream inspection."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

from ._core import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_LINE_SIZE_BYTES,
    DEFAULT_MAX_LINES,
    DEFAULT_MAX_RECORD_SIZE_BYTES,
    DEFAULT_MAX_RECORDS,
    DEFAULT_MAX_SECTIONS,
)
from ._core import detect_format_bytes as _detect_format_bytes
from ._core import scan_mi_records as _scan_mi_records
from .diagnostics import Diagnostic, DiagnosticSeverity, SourceSpan

PathSource: TypeAlias = str | os.PathLike[str]
BytesSource: TypeAlias = bytes | bytearray | memoryview
MiSource: TypeAlias = PathSource | BytesSource
FormatKind: TypeAlias = Literal["mi_text", "compressed_candidate"]
CompressionKind: TypeAlias = Literal["zlib", "gzip", "zip", "unix_compress", "unix_pack"]
LineEndingKind: TypeAlias = Literal["lf", "crlf", "cr", "none"]
LineKind: TypeAlias = Literal[
    "blank", "data", "section_marker", "entity_terminator", "file_terminator"
]
RecordTerminationKind: TypeAlias = Literal[
    "entity_marker", "section_boundary", "file_boundary", "physical_eof"
]
FileTerminationKind: TypeAlias = Literal["file_marker", "physical_eof"]


@dataclass(frozen=True, slots=True)
class ScanLimits:
    """Resource limits for one raw scan."""

    max_file_size: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_lines: int = DEFAULT_MAX_LINES
    max_sections: int = DEFAULT_MAX_SECTIONS
    max_records: int = DEFAULT_MAX_RECORDS
    max_line_size: int = DEFAULT_MAX_LINE_SIZE_BYTES
    max_record_size: int = DEFAULT_MAX_RECORD_SIZE_BYTES
    max_decompressed_size: int = DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO

    def as_core_list(self) -> list[int]:
        values = [
            self.max_file_size,
            self.max_lines,
            self.max_sections,
            self.max_records,
            self.max_line_size,
            self.max_record_size,
            self.max_decompressed_size,
            self.max_compression_ratio,
        ]
        names = [
            "max_file_size",
            "max_lines",
            "max_sections",
            "max_records",
            "max_line_size",
            "max_record_size",
            "max_decompressed_size",
            "max_compression_ratio",
        ]
        for name, value in zip(names, values, strict=True):
            _validate_limit(name, value)
        return values


@dataclass(frozen=True, slots=True)
class MiFormatInfo:
    """Conservative identification of text MI or a compression candidate."""

    kind: FormatKind
    compression: CompressionKind | None
    first_section: int | None
    utf8_bom: bool

    @property
    def is_text(self) -> bool:
        return self.kind == "mi_text"

    @property
    def is_compressed_candidate(self) -> bool:
        return self.kind == "compressed_candidate"


@dataclass(frozen=True, slots=True)
class NewlineSummary:
    lf: int
    crlf: int
    cr: int
    unterminated: int


@dataclass(frozen=True, slots=True)
class RawLine:
    """One physical line including its original line ending."""

    index: int
    number: int
    span: SourceSpan
    content_span: SourceSpan
    ending: LineEndingKind
    kind: LineKind
    section_number: int | None
    _raw_view: memoryview = field(repr=False)
    _content_view: memoryview = field(repr=False)

    @property
    def raw_view(self) -> memoryview:
        return self._raw_view

    @property
    def raw_bytes(self) -> bytes:
        return self._raw_view.tobytes()

    @property
    def content_view(self) -> memoryview:
        return self._content_view

    @property
    def content_bytes(self) -> bytes:
        return self._content_view.tobytes()


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One `|~`-framed entity or unframed section payload."""

    index: int
    section_index: int
    section_number: int
    span: SourceSpan
    payload_span: SourceSpan
    terminator_span: SourceSpan | None
    termination: RecordTerminationKind
    record_type: str | None
    _raw_view: memoryview = field(repr=False)
    _payload_view: memoryview = field(repr=False)
    _terminator_view: memoryview | None = field(repr=False)

    @property
    def raw_view(self) -> memoryview:
        return self._raw_view

    @property
    def raw_bytes(self) -> bytes:
        return self._raw_view.tobytes()

    @property
    def payload_view(self) -> memoryview:
        return self._payload_view

    @property
    def payload(self) -> bytes:
        return self._payload_view.tobytes()

    @property
    def terminator_view(self) -> memoryview | None:
        return self._terminator_view


@dataclass(frozen=True, slots=True)
class RawSection:
    """One `#~N` marker, its complete body, and logical records."""

    index: int
    number: int
    span: SourceSpan
    marker_span: SourceSpan
    body_span: SourceSpan
    records: tuple[RawRecord, ...]
    _raw_view: memoryview = field(repr=False)
    _marker_view: memoryview = field(repr=False)
    _body_view: memoryview = field(repr=False)

    @property
    def raw_view(self) -> memoryview:
        return self._raw_view

    @property
    def raw_bytes(self) -> bytes:
        return self._raw_view.tobytes()

    @property
    def marker_view(self) -> memoryview:
        return self._marker_view

    @property
    def body_view(self) -> memoryview:
        return self._body_view


@dataclass(frozen=True, slots=True)
class RawScan:
    """Complete result of one bounded, byte-preserving logical MI scan."""

    format: MiFormatInfo
    lines: tuple[RawLine, ...]
    sections: tuple[RawSection, ...]
    records: tuple[RawRecord, ...]
    diagnostics: tuple[Diagnostic, ...]
    preamble_span: SourceSpan
    file_terminator_span: SourceSpan | None
    termination: FileTerminationKind
    end_offset: int
    trailing_bytes: int
    container_size: int
    source_size: int
    newlines: NewlineSummary
    _source_view: memoryview = field(repr=False)
    _container_view: memoryview = field(repr=False)

    @property
    def source_view(self) -> memoryview:
        return self._source_view

    @property
    def source_bytes(self) -> bytes:
        """Return the logical, decompressed MI bytes addressed by all spans."""

        return self._source_view.tobytes()

    @property
    def container_view(self) -> memoryview:
        """Return the original compressed or uncompressed input container."""

        return self._container_view

    @property
    def container_bytes(self) -> bytes:
        return self._container_view.tobytes()

    @property
    def preamble_view(self) -> memoryview:
        return _slice(self._source_view, self.preamble_span)

    @property
    def file_terminator_view(self) -> memoryview | None:
        if self.file_terminator_span is None:
            return None
        return _slice(self._source_view, self.file_terminator_span)

    @property
    def trailing_view(self) -> memoryview:
        return self._source_view[self.end_offset :]

    def find_sections(self, number: int) -> tuple[RawSection, ...]:
        """Return all occurrences of one MI section number in source order."""

        return tuple(section for section in self.sections if section.number == number)

    def records_of_type(self, record_type: str) -> tuple[RawRecord, ...]:
        """Return framed records with an exact ASCII MI record type."""

        return tuple(record for record in self.records if record.record_type == record_type)


def detect_format(source: MiSource) -> MiFormatInfo:
    """Identify text MI or a compressed-stream candidate without using its extension."""

    data = _read_probe(source)
    return _format_from_core(_mapping(_detect_format_bytes(data)))


def scan(source: MiSource, *, limits: ScanLimits | None = None) -> RawScan:
    """Scan an MI stream while retaining its container and logical source bytes."""

    selected_limits = limits or ScanLimits()
    core_limits = selected_limits.as_core_list()
    data = _read_all(source, max_file_size=selected_limits.max_file_size)
    row = _mapping(_scan_mi_records(data, core_limits))
    return _scan_from_core(data, row)


scan_records = scan


def _scan_from_core(data: bytes, row: Mapping[str, Any]) -> RawScan:
    logical_source = row["logical_source"]
    logical_data = data if logical_source is None else bytes(logical_source)
    source_view = memoryview(logical_data)
    container_view = memoryview(data)
    records = tuple(_record_from_core(source_view, _mapping(item)) for item in row["records"])
    lines = tuple(_line_from_core(source_view, _mapping(item)) for item in row["lines"])
    sections = tuple(
        _section_from_core(source_view, records, _mapping(item)) for item in row["sections"]
    )
    diagnostics = tuple(_diagnostic_from_core(_mapping(item)) for item in row["diagnostics"])
    newline_row = _mapping(row["newlines"])
    terminator_row = row["file_terminator"]
    return RawScan(
        format=_format_from_core(_mapping(row["format"])),
        lines=lines,
        sections=sections,
        records=records,
        diagnostics=diagnostics,
        preamble_span=_span_from_core(_mapping(row["preamble"])),
        file_terminator_span=(
            None if terminator_row is None else _span_from_core(_mapping(terminator_row))
        ),
        termination=cast(FileTerminationKind, row["termination"]),
        end_offset=int(row["end_offset"]),
        trailing_bytes=int(row["trailing_bytes"]),
        container_size=int(row["container_size"]),
        source_size=int(row["source_size"]),
        newlines=NewlineSummary(
            lf=int(newline_row["lf"]),
            crlf=int(newline_row["crlf"]),
            cr=int(newline_row["cr"]),
            unterminated=int(newline_row["unterminated"]),
        ),
        _source_view=source_view,
        _container_view=container_view,
    )


def _line_from_core(source: memoryview, row: Mapping[str, Any]) -> RawLine:
    span = _span_from_core(_mapping(row["span"]))
    content_span = _span_from_core(_mapping(row["content_span"]))
    return RawLine(
        index=int(row["index"]),
        number=int(row["number"]),
        span=span,
        content_span=content_span,
        ending=cast(LineEndingKind, row["ending"]),
        kind=cast(LineKind, row["kind"]),
        section_number=(None if row["section_number"] is None else int(row["section_number"])),
        _raw_view=_slice(source, span),
        _content_view=_slice(source, content_span),
    )


def _record_from_core(source: memoryview, row: Mapping[str, Any]) -> RawRecord:
    span = _span_from_core(_mapping(row["span"]))
    payload_span = _span_from_core(_mapping(row["payload_span"]))
    terminator_row = row["terminator_span"]
    terminator_span = None if terminator_row is None else _span_from_core(_mapping(terminator_row))
    return RawRecord(
        index=int(row["index"]),
        section_index=int(row["section_index"]),
        section_number=int(row["section_number"]),
        span=span,
        payload_span=payload_span,
        terminator_span=terminator_span,
        termination=cast(RecordTerminationKind, row["termination"]),
        record_type=(None if row["record_type"] is None else str(row["record_type"])),
        _raw_view=_slice(source, span),
        _payload_view=_slice(source, payload_span),
        _terminator_view=None if terminator_span is None else _slice(source, terminator_span),
    )


def _section_from_core(
    source: memoryview,
    records: tuple[RawRecord, ...],
    row: Mapping[str, Any],
) -> RawSection:
    span = _span_from_core(_mapping(row["span"]))
    marker_span = _span_from_core(_mapping(row["marker_span"]))
    body_span = _span_from_core(_mapping(row["body_span"]))
    first_record = int(row["first_record"])
    record_count = int(row["record_count"])
    return RawSection(
        index=int(row["index"]),
        number=int(row["number"]),
        span=span,
        marker_span=marker_span,
        body_span=body_span,
        records=records[first_record : first_record + record_count],
        _raw_view=_slice(source, span),
        _marker_view=_slice(source, marker_span),
        _body_view=_slice(source, body_span),
    )


def _diagnostic_from_core(row: Mapping[str, Any]) -> Diagnostic:
    return Diagnostic(
        severity=cast(DiagnosticSeverity, row["severity"]),
        code=str(row["code"]),
        message=str(row["message"]),
        span=_span_from_core(_mapping(row["span"])),
        action=None if row["action"] is None else str(row["action"]),
    )


def _format_from_core(row: Mapping[str, Any]) -> MiFormatInfo:
    return MiFormatInfo(
        kind=cast(FormatKind, row["kind"]),
        compression=cast(CompressionKind | None, row["compression"]),
        first_section=None if row["first_section"] is None else int(row["first_section"]),
        utf8_bom=bool(row["utf8_bom"]),
    )


def _span_from_core(row: Mapping[str, Any]) -> SourceSpan:
    return SourceSpan(
        offset=int(row["offset"]),
        length=int(row["length"]),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
    )


def _slice(source: memoryview, span: SourceSpan) -> memoryview:
    return source[span.offset : span.end_offset]


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value)


def _read_probe(source: MiSource) -> bytes:
    if isinstance(source, (str, os.PathLike)):
        with Path(source).open("rb") as stream:
            return stream.read(64 * 1024)
    return bytes(memoryview(source)[: 64 * 1024])


def _read_all(source: MiSource, *, max_file_size: int) -> bytes:
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        with path.open("rb") as stream:
            # Check the opened handle, rather than the path, then retain a bounded
            # read in case a regular file grows after fstat or the source is not a
            # regular file at all.
            size = os.fstat(stream.fileno()).st_size
            if size > max_file_size:
                _raise_input_limit(size, max_file_size)
            read_size = min(max_file_size, os.sys.maxsize - 1) + 1
            data = stream.read(read_size)
    else:
        view = memoryview(source)
        if view.nbytes > max_file_size:
            _raise_input_limit(view.nbytes, max_file_size)
        data = view.tobytes()

    if len(data) > max_file_size:
        _raise_input_limit(len(data), max_file_size)
    return data


def _raise_input_limit(actual: int, limit: int) -> None:
    from ._core import MiLimitError

    raise MiLimitError(f"input bytes value {actual} exceeds configured limit {limit}")


def _validate_limit(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
