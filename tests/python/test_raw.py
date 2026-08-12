from __future__ import annotations

import gzip
from pathlib import Path

import pytest

import ezmi

FIXTURE = Path(__file__).parents[1] / "data" / "minimal.mi"


def test_scan_preserves_every_source_line_and_record_view() -> None:
    data = FIXTURE.read_bytes()
    result = ezmi.scan(FIXTURE)

    assert result.format == ezmi.MiFormatInfo(
        kind="mi_text", compression=None, first_section=2, utf8_bom=False
    )
    assert result.termination == "file_marker"
    assert result.trailing_bytes == 0
    assert result.container_size == len(data)
    assert result.container_bytes == data
    assert result.source_bytes == data
    assert b"".join(line.raw_bytes for line in result.lines) == data
    assert result.source_view.readonly
    assert [section.number for section in result.sections] == [2, 3, 41, 5, 6, 61, 62, 71, 72]
    assert [record.record_type for record in result.records_of_type("P")] == ["P"]
    assert len(result.records_of_type("MYSTERY")) == 1
    assert result.find_sections(61)[0].records[0].payload.startswith(b"P\n4\n")
    assert result.file_terminator_view is not None
    assert result.file_terminator_view.tobytes() == b"##~~\n"
    assert result.diagnostics == ()


def test_scan_preserves_crlf_and_reports_missing_file_marker() -> None:
    data = b"#~61\r\nP\r\n1\r\n0\r\n0\r\n|~\r\n"
    result = ezmi.scan(data)

    assert result.newlines.crlf == 6
    assert result.newlines.lf == 0
    assert result.records[0].raw_bytes == b"P\r\n1\r\n0\r\n0\r\n|~\r\n"
    assert result.termination == "physical_eof"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"MI_MISSING_FILE_TERMINATOR"}


def test_unterminated_entity_record_remains_accessible() -> None:
    result = ezmi.scan(b"#~62\nLIN\n1\n2\n##~~\n")

    assert len(result.records) == 1
    assert result.records[0].record_type is None
    assert result.records[0].termination == "file_boundary"
    assert result.records[0].payload == b"LIN\n1\n2\n"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"MI_UNTERMINATED_RECORD"}


def test_symbol_section_requires_entity_terminators() -> None:
    result = ezmi.scan(b"#~82\nSYML\n1\n0\n0\n##~~\n")

    assert result.records[0].termination == "file_boundary"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"MI_UNTERMINATED_RECORD"}


def test_gzip_container_is_decoded_without_losing_either_byte_stream() -> None:
    data = FIXTURE.read_bytes()
    compressed = gzip.compress(data, mtime=0)

    candidate = ezmi.detect_format(compressed)
    assert candidate.kind == "compressed_candidate"
    assert candidate.compression == "gzip"

    result = ezmi.scan(compressed)
    assert result.format == ezmi.MiFormatInfo(
        kind="mi_text", compression="gzip", first_section=2, utf8_bom=False
    )
    assert result.container_size == len(compressed)
    assert result.source_size == len(data)
    assert result.container_bytes == compressed
    assert result.source_bytes == data
    assert b"".join(line.raw_bytes for line in result.lines) == data


def test_unverified_compression_families_remain_unsupported() -> None:
    zlib_candidate = bytes.fromhex("789c0300")
    info = ezmi.detect_format(zlib_candidate)

    assert info.kind == "compressed_candidate"
    assert info.compression == "zlib"
    with pytest.raises(ezmi.UnsupportedMiError, match="not supported"):
        ezmi.scan(zlib_candidate)


def test_gzip_limits_and_stream_integrity_are_enforced() -> None:
    data = FIXTURE.read_bytes()
    compressed = gzip.compress(data, mtime=0)

    with pytest.raises(ezmi.MiLimitError, match="input bytes"):
        ezmi.scan(compressed, limits=ezmi.ScanLimits(max_file_size=len(compressed) - 1))

    with pytest.raises(ezmi.MiLimitError, match="decompressed bytes"):
        ezmi.scan(compressed, limits=ezmi.ScanLimits(max_decompressed_size=len(data) - 1))

    with pytest.raises(ezmi.MiLimitError, match="compression ratio"):
        ezmi.scan(compressed, limits=ezmi.ScanLimits(max_compression_ratio=1))

    with pytest.raises(ezmi.InvalidMiError, match="invalid gzip"):
        ezmi.scan(compressed[:-4])

    with pytest.raises(ezmi.InvalidMiError, match="additional gzip members"):
        ezmi.scan(compressed + gzip.compress(data, mtime=0))


def test_limits_are_enforced_before_and_during_scan() -> None:
    with pytest.raises(ezmi.MiLimitError, match="input bytes"):
        ezmi.scan(FIXTURE, limits=ezmi.ScanLimits(max_file_size=4))

    with pytest.raises(ezmi.MiLimitError, match="input bytes"):
        ezmi.scan(memoryview(bytearray(8)), limits=ezmi.ScanLimits(max_file_size=4))

    with pytest.raises(ezmi.MiLimitError, match="line count"):
        ezmi.scan(FIXTURE, limits=ezmi.ScanLimits(max_lines=1))

    with pytest.raises(ValueError, match="non-negative"):
        ezmi.scan(FIXTURE, limits=ezmi.ScanLimits(max_records=-1))


def test_format_detection_is_extension_independent_and_supports_utf8_bom() -> None:
    info = ezmi.detect_format(b"\xef\xbb\xbf\r\n#~1\r\n##~~\r\n")
    assert info.first_section == 1
    assert info.utf8_bom

    with pytest.raises(ezmi.InvalidMiError):
        ezmi.detect_format(b"// mental ray scene\n")
