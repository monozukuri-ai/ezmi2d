"""Command-line inspection for raw MI streams."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import MiError, RawScan, __version__, scan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ezmi", description="Inspect MI drawing streams")
    parser.add_argument("--version", action="version", version=f"ezmi {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="scan one MI stream without semantic decoding")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--json", action="store_true", dest="as_json")
    inspect.add_argument("--records", action="store_true", help="include record summaries")
    inspect.add_argument("--lines", action="store_true", help="include physical line summaries")
    return parser


def _summary(scan_result: RawScan, *, records: bool, lines: bool) -> dict[str, Any]:
    record_types = Counter(
        record.record_type for record in scan_result.records if record.record_type is not None
    )
    result: dict[str, Any] = {
        "format": {
            "kind": scan_result.format.kind,
            "compression": scan_result.format.compression,
            "first_section": scan_result.format.first_section,
            "utf8_bom": scan_result.format.utf8_bom,
        },
        "container_size": scan_result.container_size,
        "source_size": scan_result.source_size,
        "termination": scan_result.termination,
        "end_offset": scan_result.end_offset,
        "trailing_bytes": scan_result.trailing_bytes,
        "line_count": len(scan_result.lines),
        "section_count": len(scan_result.sections),
        "record_count": len(scan_result.records),
        "record_types": dict(sorted(record_types.items())),
        "newlines": {
            "lf": scan_result.newlines.lf,
            "crlf": scan_result.newlines.crlf,
            "cr": scan_result.newlines.cr,
            "unterminated": scan_result.newlines.unterminated,
        },
        "sections": [
            {
                "index": section.index,
                "number": section.number,
                "offset": section.span.offset,
                "length": section.span.length,
                "record_count": len(section.records),
            }
            for section in scan_result.sections
        ],
        "diagnostics": [
            {
                "severity": diagnostic.severity,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "offset": diagnostic.span.offset,
                "length": diagnostic.span.length,
                "start_line": diagnostic.span.start_line,
                "end_line": diagnostic.span.end_line,
                "action": diagnostic.action,
            }
            for diagnostic in scan_result.diagnostics
        ],
    }
    if records:
        result["records"] = [
            {
                "index": record.index,
                "section": record.section_number,
                "type": record.record_type,
                "offset": record.span.offset,
                "length": record.span.length,
                "termination": record.termination,
            }
            for record in scan_result.records
        ]
    if lines:
        result["lines"] = [
            {
                "number": line.number,
                "offset": line.span.offset,
                "length": line.span.length,
                "ending": line.ending,
                "kind": line.kind,
                "section": line.section_number,
            }
            for line in scan_result.lines
        ]
    return result


def _print_text(path: Path, summary: dict[str, Any]) -> None:
    print(f"path: {path}")
    print(f"format: {summary['format']['kind']}")
    if summary["format"]["compression"] is None:
        print(f"size: {summary['source_size']} bytes")
    else:
        print(
            f"size: {summary['source_size']} logical bytes from "
            f"{summary['container_size']} compressed bytes"
        )
    print(f"termination: {summary['termination']}")
    print(
        "structure: "
        f"{summary['line_count']} lines, "
        f"{summary['section_count']} sections, "
        f"{summary['record_count']} records"
    )
    record_types = summary["record_types"]
    if record_types:
        print(
            "record types: " + ", ".join(f"{name}={count}" for name, count in record_types.items())
        )
    diagnostics = summary["diagnostics"]
    print(f"diagnostics: {len(diagnostics)}")
    for diagnostic in diagnostics:
        print(
            f"  {diagnostic['severity']} {diagnostic['code']} "
            f"at byte {diagnostic['offset']}: {diagnostic['message']}"
        )
    if "records" in summary:
        print("records:")
        for record in summary["records"]:
            print(
                f"  [{record['index']}] #~{record['section']} "
                f"{record['type'] or '<unframed>'} "
                f"offset={record['offset']} length={record['length']} "
                f"termination={record['termination']}"
            )
    if "lines" in summary:
        print("lines:")
        for line in summary["lines"]:
            print(
                f"  {line['number']}: offset={line['offset']} length={line['length']} "
                f"ending={line['ending']} kind={line['kind']}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "inspect":  # pragma: no cover - required subparser
        raise AssertionError(args.command)

    try:
        scan_result = scan(args.path)
    except (MiError, OSError) as error:
        print(f"ezmi: error: {error}", file=sys.stderr)
        return 1

    summary = _summary(scan_result, records=args.records, lines=args.lines)
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(args.path, summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
