from __future__ import annotations

import json
from pathlib import Path

from ezmi2d.__main__ import main

FIXTURE = Path(__file__).parents[1] / "data" / "minimal.mi"


def test_inspect_json_reports_raw_structure(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["inspect", str(FIXTURE), "--json", "--records"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["format"]["kind"] == "mi_text"
    assert payload["termination"] == "file_marker"
    assert payload["section_count"] == 9
    assert payload["record_types"]["P"] == 1
    assert any(record["type"] == "MYSTERY" for record in payload["records"])


def test_inspect_returns_nonzero_for_invalid_input(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "not-mi.mi"
    path.write_bytes(b"not an MI stream")

    assert main(["inspect", str(path)]) == 1
    assert "not have a recognized MI" in capsys.readouterr().err


def test_inspect_text_can_list_records_and_lines(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["inspect", str(FIXTURE), "--records", "--lines"]) == 0
    output = capsys.readouterr().out

    assert "records:" in output
    assert "#~62 MYSTERY" in output
    assert "lines:" in output
    assert "kind=file_terminator" in output
