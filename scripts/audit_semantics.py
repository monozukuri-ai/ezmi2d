#!/usr/bin/env python3
"""Audit MI semantic coverage without assigning unverified field meanings."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import ezmi2d


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit raw layouts and typed ezmi2d semantic coverage."
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="MI files or directories")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def _candidate_paths(inputs: Sequence[Path]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for input_path in inputs:
        if input_path.is_dir():
            candidates.extend(path for path in input_path.rglob("*") if path.is_file())
        else:
            candidates.append(input_path)
    return tuple(sorted(dict.fromkeys(path.resolve() for path in candidates)))


def _counter(counter: Counter[object]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=str)}


def _bytes_tuple(values: Iterable[bytes]) -> str:
    decoded = (value.decode("ascii", errors="backslashreplace") for value in values)
    return repr(tuple(decoded))


def _float_tuple(values: Iterable[float]) -> str:
    return repr(tuple(float(value) for value in values))


def _new_record_stats() -> dict[str, Counter[object]]:
    return {
        "field_counts": Counter(),
        "terminal_field_values": Counter(),
    }


def audit(inputs: Sequence[Path]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    raw_counts: Counter[str] = Counter()
    typed_counts: Counter[str] = Counter()
    unsupported_counts: Counter[str] = Counter()
    record_stats: defaultdict[str, dict[str, Counter[object]]] = defaultdict(_new_record_stats)
    arc_orientations: defaultdict[str, Counter[object]] = defaultdict(Counter)
    arc_ccw: defaultdict[str, Counter[object]] = defaultdict(Counter)
    assembly_transforms: Counter[str] = Counter()
    bspline_stats: defaultdict[str, Counter[object]] = defaultdict(Counter)
    graphic_stats: defaultdict[str, Counter[object]] = defaultdict(Counter)
    dimension_stats: defaultdict[str, Counter[object]] = defaultdict(Counter)
    annotation_stats: defaultdict[str, Counter[object]] = defaultdict(Counter)
    property_models: Counter[str] = Counter()

    for path in _candidate_paths(inputs):
        data = path.read_bytes()
        try:
            document = ezmi2d.read(data)
        except (ezmi2d.MiError, ValueError) as error:
            skipped.append({"path": str(path), "reason": str(error)})
            continue

        raw_file_counts: Counter[str] = Counter()
        for record in document.raw.records:
            if record.record_type is None:
                continue
            mi_type = record.record_type
            fields = record.payload.splitlines()
            raw_counts[mi_type] += 1
            raw_file_counts[mi_type] += 1
            record_stats[mi_type]["field_counts"][len(fields)] += 1
            if mi_type in {"ARC", "FIL"} and fields:
                terminal = fields[-1].decode("ascii", errors="backslashreplace")
                record_stats[mi_type]["terminal_field_values"][terminal] += 1

        for entity in document.all_entities:
            if isinstance(entity, ezmi2d.UnsupportedEntity):
                unsupported_counts[entity.mi_type] += 1
                continue
            typed_counts[entity.mi_type] += 1
            if isinstance(entity, ezmi2d.Property):
                property_models[type(entity).__name__] += 1
            if isinstance(entity, ezmi2d.GraphicEntity):
                graphic_stats["colors"][entity.color] += 1
                graphic_stats["linetypes"][entity.linetype] += 1
                graphic_stats["lineweights"][entity.lineweight] += 1
                graphic_stats["visibility"][entity.visibility] += 1
                graphic_stats["visibility_values"][entity.visibility_value] += 1
                graphic_stats["property_counts"][len(entity.property_ids)] += 1
                graphic_stats["layer_counts"][len(entity.layers)] += 1
            if isinstance(entity, (ezmi2d.Arc, ezmi2d.Fillet)):
                arc_orientations[entity.mi_type][entity.orientation] += 1
                arc_ccw[entity.mi_type][getattr(entity, "ccw", None)] += 1
            elif isinstance(entity, ezmi2d.Assembly):
                for instance in entity.instances:
                    assembly_transforms[_float_tuple(instance.transform_values)] += 1
            elif isinstance(entity, ezmi2d.BSpline):
                bspline_stats["definition_values"][_bytes_tuple(entity.definition_values)] += 1
                bspline_stats["prefix_lengths"][len(entity.prefix_values)] += 1
                bspline_stats["orders"][entity.order] += 1
                bspline_stats["control_point_counts"][len(entity.control_point_ids)] += 1
                bspline_stats["weight_presence"][getattr(entity, "weights", None) is not None] += 1
                for name in ("closed", "periodic", "rational"):
                    bspline_stats[name][getattr(entity, name, None)] += 1
            elif isinstance(entity, ezmi2d.Dimension):
                dimension_stats["types"][entity.mi_type] += 1
                dimension_stats["geometry_reference_counts"][
                    len(entity.reference_geometry_ids)
                ] += 1
                dimension_stats["point_reference_counts"][len(entity.reference_point_ids)] += 1
                dimension_stats["unresolved_geometry"][
                    sum(value is None for value in entity.reference_geometries)
                ] += 1
                dimension_stats["unresolved_points"][
                    sum(value is None for value in entity.reference_points)
                ] += 1
                dimension_stats["tolerance_counts"][len(entity.tolerance_ids)] += 1
                dimension_stats["decoded_text"][entity.formatted_text is not None] += 1
            elif isinstance(entity, ezmi2d.DimensionTolerance):
                annotation_stats["dtv_decoded_text"][
                    entity.upper_text is not None and entity.lower_text is not None
                ] += 1
            elif isinstance(entity, ezmi2d.Leader):
                annotation_stats["leader_vertex_counts"][len(entity.vertices)] += 1
            elif isinstance(entity, ezmi2d.Contour):
                annotation_stats["contour_component_counts"][len(entity.component_ids)] += 1
                annotation_stats["contour_unresolved_components"][
                    sum(value is None for value in entity.components)
                ] += 1
            elif isinstance(entity, ezmi2d.Hatch):
                annotation_stats["hatch_boundary_counts"][len(entity.boundary_loop_ids)] += 1
                annotation_stats["hatch_pattern_present"][entity.pattern is not None] += 1
            elif isinstance(entity, ezmi2d.Symbol):
                annotation_stats["symbol_component_counts"][len(entity.component_ids)] += 1
                annotation_stats["symbol_unresolved_components"][
                    sum(value is None for value in entity.components)
                ] += 1

        files.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(data).hexdigest(),
                "container_bytes": len(data),
                "logical_bytes": document.raw.source_size,
                "version": document.version,
                "encoding": document.encoding,
                "compression": document.raw.format.compression,
                "raw_record_counts": _counter(raw_file_counts),
                "typed_entities": sum(
                    not isinstance(entity, ezmi2d.UnsupportedEntity)
                    for entity in document.all_entities
                ),
                "unsupported_entities": len(document.unsupported_entities),
                "diagnostic_codes": _counter(
                    Counter(diagnostic.code for diagnostic in document.diagnostics)
                ),
            }
        )

    records = {
        mi_type: {
            "count": raw_counts[mi_type],
            "field_counts": _counter(values["field_counts"]),
            "terminal_field_values": _counter(values["terminal_field_values"]),
        }
        for mi_type, values in sorted(record_stats.items())
    }
    return {
        "schema_version": 1,
        "files": files,
        "skipped": skipped,
        "totals": {
            "files": len(files),
            "raw_records": _counter(raw_counts),
            "typed_entities": _counter(typed_counts),
            "unsupported_entities": _counter(unsupported_counts),
        },
        "records": records,
        "arc_direction": {
            mi_type: {
                "orientation": _counter(arc_orientations[mi_type]),
                "ccw": _counter(arc_ccw[mi_type]),
            }
            for mi_type in sorted(set(arc_orientations) | set(arc_ccw))
        },
        "assembly": {"transform_values": _counter(assembly_transforms)},
        "bspline": {name: _counter(values) for name, values in sorted(bspline_stats.items())},
        "graphics": {name: _counter(values) for name, values in sorted(graphic_stats.items())},
        "dimensions": {name: _counter(values) for name, values in sorted(dimension_stats.items())},
        "annotations": {
            name: _counter(values) for name, values in sorted(annotation_stats.items())
        },
        "property_models": _counter(property_models),
    }


def _markdown_table(rows: Iterable[tuple[str, object, object, object]]) -> list[str]:
    lines = [
        "| MI type | raw | typed | unsupported |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| `{name}` | {raw} | {typed} | {unsupported} |" for name, raw, typed, unsupported in rows
    )
    return lines


def markdown(report: Mapping[str, Any]) -> str:
    totals = report["totals"]
    raw = totals["raw_records"]
    typed = totals["typed_entities"]
    unsupported = totals["unsupported_entities"]
    names = sorted(set(raw) | set(typed) | set(unsupported))
    lines = [
        "# ezmi2d semantic audit",
        "",
        f"Files decoded: **{totals['files']}**; skipped: **{len(report['skipped'])}**.",
        "",
        "## Coverage",
        "",
        *_markdown_table(
            (name, raw.get(name, 0), typed.get(name, 0), unsupported.get(name, 0)) for name in names
        ),
        "",
        "## Arc direction evidence",
        "",
    ]
    if report["arc_direction"]:
        for mi_type, values in report["arc_direction"].items():
            terminal = report["records"].get(mi_type, {}).get("terminal_field_values", {})
            lines.append(
                f"- `{mi_type}`: orientation={values['orientation']}; "
                f"ccw={values['ccw']}; raw terminal field={terminal}."
            )
    else:
        lines.append("- No typed ARC/FIL entities were found.")
    lines.extend(
        [
            "",
            "## Assembly transform evidence",
            "",
            f"- Serialized 3x3 values: {report['assembly']['transform_values']}",
            "",
            "## B-spline evidence",
            "",
        ]
    )
    if report["bspline"]:
        lines.extend(f"- `{name}`: {values}" for name, values in report["bspline"].items())
    else:
        lines.append("- No typed BSPL entities were found.")
    lines.extend(["", "## Graphic and annotation evidence", ""])
    lines.extend(f"- Graphic `{name}`: {values}" for name, values in report["graphics"].items())
    lines.extend(f"- Dimension `{name}`: {values}" for name, values in report["dimensions"].items())
    lines.extend(
        f"- Annotation `{name}`: {values}" for name, values in report["annotations"].items()
    )
    lines.append(f"- Property models: {report['property_models']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parser().parse_args()
    report = audit(args.inputs)
    json_text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    markdown_text = markdown(report)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json_text, encoding="utf-8")
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_text, encoding="utf-8")
    if args.json_output is None and args.markdown_output is None:
        print(json_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
