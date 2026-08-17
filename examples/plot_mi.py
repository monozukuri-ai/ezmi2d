#!/usr/bin/env python3
"""Render decoded MI geometry to a PNG for visual inspection."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import ezmi2d


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="MI/BI input path (extension is not required)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="output PNG path")
    parser.add_argument("--encoding", help="explicit MI text encoding override")
    parser.add_argument(
        "--part-index",
        type=int,
        help="draw only this zero-based part definition (default: all definitions)",
    )
    parser.add_argument(
        "--curve-segments",
        type=int,
        default=128,
        help="segments per arc, circle, or B-spline (default: 128)",
    )
    parser.add_argument("--points", action="store_true", help="show decoded P records")
    parser.add_argument("--no-text", action="store_true", help="hide TEX content")
    parser.add_argument("--font-family", help="Matplotlib font family used for TEX content")
    parser.add_argument("--dpi", type=int, default=160, help="output resolution (default: 160)")
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()

    try:
        import matplotlib
    except ImportError as error:
        parser.exit(
            2,
            f"Matplotlib is unavailable: {error}\nInstall with `pip install 'ezmi2d[plot]'`.\n",
        )

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    drawing = ezmi2d.read(args.input, encoding=args.encoding)
    if args.part_index is None:
        source: ezmi2d.Document | ezmi2d.Part = drawing
        source_name = "all part definitions"
    else:
        if not 0 <= args.part_index < len(drawing.parts):
            parser.error(
                f"--part-index must be between 0 and {len(drawing.parts) - 1} for this file"
            )
        source = drawing.parts[args.part_index]
        source_name = f"part {args.part_index}: {source.name or '<undecoded>'}"

    figure, axes = plt.subplots(figsize=(12, 8), constrained_layout=True)
    ezmi2d.draw(
        source,
        ax=axes,
        curve_segments=args.curve_segments,
        show_points=args.points,
        show_text=not args.no_text,
        text_font_family=args.font_family,
    )
    units = drawing.units or "drawing units"
    axes.set_xlabel(f"x [{units}]")
    axes.set_ylabel(f"y [{units}]")
    axes.set_title(f"{args.input.name} — {source_name}")
    axes.grid(True, color="#d1d5db", linewidth=0.4)
    handles, labels = axes.get_legend_handles_labels()
    if handles:
        axes.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            borderaxespad=0.0,
            fontsize="small",
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=args.dpi, bbox_inches="tight")
    plt.close(figure)

    counts = Counter(entity.mi_type for entity in source.entities)
    summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items())) or "none"
    print(f"parsed {len(source.entities)} graphic entities ({summary})")
    print(f"diagnostics: {len(drawing.diagnostics)}")
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
