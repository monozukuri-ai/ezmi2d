#!/usr/bin/env python3
"""Benchmark distinct ezmi reader stages and emit JSON plus Markdown reports."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import platform
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import ezmi

SCHEMA_VERSION = 1
STAGE_DESCRIPTIONS = {
    "read_container": "Path.read_bytes(); container I/O only",
    "detect_format_bytes": "ezmi.detect_format(bytes); signature/probe only",
    "scan_bytes": "ezmi.scan(bytes); decompression, raw scan, and Python raw model",
    "read_bytes": "ezmi.read(bytes); decompression, raw and semantic parse, Python model",
    "read_path_end_to_end": "ezmi.read(path); I/O through complete semantic Python model",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the complete ezmi input-to-Document pipeline"
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="MI/BI files or directories containing .mi/.bi/extensionless MI files",
    )
    parser.add_argument("--repeat", type=int, default=5, help="timed runs per file and stage")
    parser.add_argument("--warmup", type=int, default=1, help="untimed runs per stage")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser


def _expand_inputs(inputs: Sequence[Path]) -> list[Path]:
    paths: set[Path] = set()
    for candidate in inputs:
        if candidate.is_file():
            paths.add(candidate.resolve())
            continue
        if not candidate.is_dir():
            raise FileNotFoundError(candidate)
        for path in candidate.rglob("*"):
            if path.is_file() and path.suffix.lower() in {"", ".mi", ".bi"}:
                paths.add(path.resolve())
    if not paths:
        raise ValueError("no MI/BI inputs were selected")
    return sorted(paths)


def _measure(operation: Callable[[], object], *, warmup: int, repeat: int) -> list[int]:
    for _ in range(warmup):
        result = operation()
        del result

    samples: list[int] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(repeat):
            started = perf_counter_ns()
            result = operation()
            finished = perf_counter_ns()
            samples.append(finished - started)
            del result
    finally:
        if gc_was_enabled:
            gc.enable()
    return samples


def _statistics(samples_ns: Sequence[int]) -> dict[str, Any]:
    ordered = sorted(samples_ns)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "samples_ns": list(samples_ns),
        "min_ns": min(samples_ns),
        "median_ns": int(statistics.median(samples_ns)),
        "mean_ns": int(statistics.fmean(samples_ns)),
        "p95_ns": ordered[p95_index],
    }


def _display_path(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _benchmark_file(path: Path, *, warmup: int, repeat: int, base: Path) -> dict[str, Any]:
    container = path.read_bytes()
    format_info = ezmi.detect_format(container)
    raw = ezmi.scan(container)
    document = ezmi.read(container)

    operations: dict[str, Callable[[], object]] = {
        "read_container": path.read_bytes,
        "detect_format_bytes": lambda: ezmi.detect_format(container),
        "scan_bytes": lambda: ezmi.scan(container),
        "read_bytes": lambda: ezmi.read(container),
        "read_path_end_to_end": lambda: ezmi.read(path),
    }
    stages = {
        name: _statistics(_measure(operation, warmup=warmup, repeat=repeat))
        for name, operation in operations.items()
    }
    return {
        "path": _display_path(path, base),
        "sha256": hashlib.sha256(container).hexdigest(),
        "container_size": len(container),
        "logical_size": raw.source_size,
        "compression": format_info.compression,
        "line_count": len(raw.lines),
        "record_count": len(raw.records),
        "entity_count": len(document.all_entities),
        "diagnostic_count": len(document.diagnostics),
        "stages": stages,
    }


def _aggregate(files: Sequence[dict[str, Any]]) -> dict[str, Any]:
    container_bytes = sum(row["container_size"] for row in files)
    logical_bytes = sum(row["logical_size"] for row in files)
    probe_bytes = sum(min(row["container_size"], 64 * 1024) for row in files)
    stages: dict[str, Any] = {}
    for name in STAGE_DESCRIPTIONS:
        duration_ns = sum(row["stages"][name]["median_ns"] for row in files)
        if name == "detect_format_bytes":
            byte_basis = probe_bytes
            byte_basis_name = "probe"
        elif name in {"scan_bytes", "read_bytes", "read_path_end_to_end"}:
            byte_basis = logical_bytes
            byte_basis_name = "logical"
        else:
            byte_basis = container_bytes
            byte_basis_name = "container"
        stages[name] = {
            "sum_of_file_medians_ns": duration_ns,
            "throughput_mib_s": (
                byte_basis / (1024 * 1024) / (duration_ns / 1_000_000_000) if duration_ns else None
            ),
            "byte_basis": byte_basis_name,
        }
    return {
        "file_count": len(files),
        "container_bytes": container_bytes,
        "logical_bytes": logical_bytes,
        "probe_bytes": probe_bytes,
        "line_count": sum(row["line_count"] for row in files),
        "record_count": sum(row["record_count"] for row in files),
        "entity_count": sum(row["entity_count"] for row in files),
        "stages": stages,
    }


def _environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "ezmi": ezmi.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def _format_ms(value_ns: int) -> str:
    return f"{value_ns / 1_000_000:.3f}"


def _markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    environment = report["environment"]
    lines = [
        "# ezmi full-pipeline benchmark",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "This snapshot reports independent, non-additive measurements. "
        "`read_path_end_to_end` is the acceptance metric for the complete path from file I/O "
        "through decompression, scanning, semantic decoding, reference resolution, and Python "
        "object materialization.",
        "",
        "## Conditions",
        "",
        f"- ezmi `{environment['ezmi']}` on Python `{environment['python']}` "
        f"({environment['python_implementation']})",
        f"- Platform: `{environment['platform']}` / `{environment['machine']}`",
        f"- Warmup runs: {report['warmup']}; timed runs: {report['repeat']} per file and stage",
        f"- Corpus: {aggregate['file_count']} files, "
        f"{aggregate['container_bytes']} container bytes, "
        f"{aggregate['logical_bytes']} logical bytes, {aggregate['record_count']} records, "
        f"{aggregate['entity_count']} addressable entities",
        "- Garbage-collector cycles are disabled during each timed loop; normal reference-count "
        "cleanup still occurs outside the timed interval.",
        "",
        "## Aggregate stages",
        "",
        "| Stage | Scope | Sum of file medians (ms) | Throughput (MiB/s) |",
        "|---|---|---:|---:|",
    ]
    for name, description in STAGE_DESCRIPTIONS.items():
        row = aggregate["stages"][name]
        throughput = row["throughput_mib_s"]
        lines.append(
            f"| `{name}` | {description} | "
            f"{_format_ms(row['sum_of_file_medians_ns'])} | "
            f"{throughput:.2f} ({row['byte_basis']}) |"
        )
    lines.extend(
        [
            "",
            "## Per-file full pipeline",
            "",
            "| Input | Container / logical bytes | Records | Entities | Median (ms) |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in report["files"]:
        stage = row["stages"]["read_path_end_to_end"]
        lines.append(
            f"| `{row['path']}` | {row['container_size']} / {row['logical_size']} | "
            f"{row['record_count']} | {row['entity_count']} | {_format_ms(stage['median_ns'])} |"
        )
    lines.extend(
        [
            "",
            "The paired JSON report contains SHA-256 input identities and every nanosecond sample. "
            "This is a development-machine snapshot, not a cross-machine performance guarantee.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be non-negative")

    base = Path.cwd().resolve()
    paths = _expand_inputs(args.inputs)
    files = [
        _benchmark_file(path, warmup=args.warmup, repeat=args.repeat, base=base) for path in paths
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warmup": args.warmup,
        "repeat": args.repeat,
        "stage_descriptions": STAGE_DESCRIPTIONS,
        "environment": _environment(),
        "aggregate": _aggregate(files),
        "files": files,
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    full_pipeline_ns = report["aggregate"]["stages"]["read_path_end_to_end"][
        "sum_of_file_medians_ns"
    ]
    print(
        f"benchmarked {len(files)} file(s); full pipeline median sum "
        f"{_format_ms(full_pipeline_ns)} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
