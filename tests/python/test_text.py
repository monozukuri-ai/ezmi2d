from __future__ import annotations

from pathlib import Path

import pytest

import ezmi

FIXTURE = Path(__file__).parents[1] / "data" / "geometry.mi"
UTF8_FIXTURE = Path(__file__).parents[1] / "data" / "text-utf8.mi"
UNKNOWN_RECORD = b"MYSTERY\n13\nopaque\n|~"


def _text_record(content: bytes, *, font_name: bytes = b"hp_i3098_v") -> bytes:
    fields = [
        b"TEX",
        b"13",
        b"3",
        b"0",
        b"1",
        b"1",
        b"2",
        b"4",
        b"1",
        b"0",
        b"25",
        b"0",
        b"1",
        b"12",
        b"0",
        b"0",
        b"1",
        b"0",
        b"0",
        font_name,
        b"0",
        b"0",
        b"3.5",
        b"3.5",
        b"0",
        b"1.5",
        b"0",
        b"1",
        content,
        b"0",
    ]
    assert len(fields) == 30
    return b"\n".join(fields) + b"\n|~"


def _text_document_bytes(
    content: bytes,
    *,
    declaration: bytes | None = b"ENCODING:SJIS",
    version: bytes = b"2.10",
    font_name: bytes = b"hp_i3098_v",
) -> bytes:
    data = FIXTURE.read_bytes()
    assert data.count(UNKNOWN_RECORD) == 1
    data = data.replace(UNKNOWN_RECORD, _text_record(content, font_name=font_name))
    if version != b"2.10":
        marker = b"\n2.10\n2D\n"
        assert data.count(marker) == 1
        data = data.replace(marker, b"\n" + version + b"\n2D\n")
    if declaration is not None:
        data = b"#~1\n" + declaration + b"\n" + data
    return data


def test_declared_shift_jis_decodes_typed_text_without_replacement() -> None:
    content = "ソアラーデックス".encode("cp932")
    document = ezmi.read(_text_document_bytes(content))

    assert document.encoding_info == ezmi.EncodingInfo("shift_jis", "declared", "SJIS")
    assert document.encoding == "shift_jis"
    assert document.encoding_source == "declared"
    assert document.declared_encoding == "SJIS"
    assert document.diagnostics == ()
    assert len(document.texts) == 1
    assert document.top_part is not None
    assert document.top_part.texts == document.texts

    text = document.texts[0]
    assert isinstance(document.get(13), ezmi.Text)
    assert document.query("TEX") == (text,)
    assert document.query("TEXT") == (text,)
    assert text.text == "ソアラーデックス"
    assert "\ufffd" not in text.text
    assert text.text_bytes == content
    assert text.content_value.encoding == "shift_jis"
    assert text.font_name == "hp_i3098_v"
    assert text.font_name_bytes == b"hp_i3098_v"
    assert text.origin == ezmi.Vec2(25.0, 12.0)
    assert text.transform_values == (1.0, 0.0, 25.0, 0.0, 1.0, 12.0, 0.0, 0.0, 1.0)
    assert text.size_values == (3.5, 3.5)
    assert text.height == pytest.approx(3.5)
    assert text.property is document.get(2)
    assert text.values[26] == content
    assert text.raw_record.record_type == "TEX"


def test_legacy_encoding_can_be_inferred_or_overridden() -> None:
    content = "日本語".encode("cp932")
    data = _text_document_bytes(content, declaration=None)

    inferred = ezmi.read(data)
    assert inferred.encoding == "shift_jis"
    assert inferred.encoding_source == "heuristic"
    assert inferred.texts[0].text == "日本語"
    assert [diagnostic.code for diagnostic in inferred.diagnostics] == ["MI_ENCODING_GUESSED"]

    overridden = ezmi.read(data, encoding="cp932")
    assert overridden.encoding_info == ezmi.EncodingInfo("shift_jis", "override", None)
    assert overridden.texts[0].text == "日本語"
    assert overridden.diagnostics == ()


def test_mi_320_uses_utf8_and_bom_has_higher_precedence() -> None:
    versioned = ezmi.read(UTF8_FIXTURE)
    assert versioned.encoding_info == ezmi.EncodingInfo("utf-8", "mi_version", "UTF-8")
    assert versioned.texts[0].text == "日本語 café"
    assert {diagnostic.code for diagnostic in versioned.diagnostics} == {
        "MI_GLOBAL_LAYOUT_UNVERIFIED"
    }

    bom_data = b"\xef\xbb\xbf" + _text_document_bytes(
        "日本語".encode(), declaration=b"ENCODING:SJIS"
    )
    bom = ezmi.read(bom_data)
    assert bom.encoding_info == ezmi.EncodingInfo("utf-8", "utf8_bom", "SJIS")
    assert bom.texts[0].text == "日本語"
    assert [diagnostic.code for diagnostic in bom.diagnostics] == ["MI_ENCODING_CONFLICT"]


def test_hp_roman8_is_supported_for_older_files() -> None:
    data = _text_document_bytes(b"caf\xc5", declaration=b"ENCODING:ROMAN8")
    document = ezmi.read(data)

    assert document.encoding_info == ezmi.EncodingInfo("hp-roman8", "declared", "ROMAN8")
    assert document.texts[0].text == "café"
    assert document.texts[0].text_bytes == b"caf\xc5"


def test_decode_error_retains_raw_bytes_and_reports_the_exact_source_byte() -> None:
    content = b"bad\x81"
    data = _text_document_bytes(content)
    invalid_offset = data.index(content) + 3

    document = ezmi.read(data)
    text = document.texts[0]
    assert text.text is None
    assert text.text_bytes == content
    assert text.content_value.encoding == "shift_jis"

    errors = [
        diagnostic
        for diagnostic in document.diagnostics
        if diagnostic.code == "MI_TEXT_DECODE_ERROR"
    ]
    assert len(errors) == 1
    assert errors[0].span.offset == invalid_offset
    assert errors[0].span.length == 1
    assert errors[0].span.start_line == errors[0].span.end_line
    assert "field byte 3" in errors[0].message


def test_unknown_declaration_is_lossless_and_override_labels_are_validated() -> None:
    content = "日本語".encode("cp932")
    data = _text_document_bytes(content, declaration=b"ENCODING:VENDOR-UNKNOWN")

    document = ezmi.read(data)
    assert document.encoding_info == ezmi.EncodingInfo(None, "declared", "VENDOR-UNKNOWN")
    assert document.texts[0].text is None
    assert document.texts[0].text_bytes == content
    assert [diagnostic.code for diagnostic in document.diagnostics] == [
        "MI_UNSUPPORTED_DECLARED_ENCODING"
    ]

    recovered = ezmi.read(data, encoding="windows-31j")
    assert recovered.encoding_info == ezmi.EncodingInfo("shift_jis", "override", "VENDOR-UNKNOWN")
    assert recovered.texts[0].text == "日本語"

    with pytest.raises(ValueError, match="unsupported MI text encoding"):
        ezmi.read(data, encoding="not-an-encoding")
