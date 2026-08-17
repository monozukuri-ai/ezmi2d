#!/usr/bin/env python3
"""Exercise an installed ezmi2d distribution without importing the source tree."""

from __future__ import annotations

import argparse
import gzip
import subprocess
import sys
from importlib.metadata import metadata, version
from pathlib import Path

import ezmi2d

PACKAGE_FILES = {
    "__init__.py",
    "__main__.py",
    "_core.pyi",
    "diagnostics.py",
    "document.py",
    "entities.py",
    "plotting.py",
    "raw.py",
    "py.typed",
}
PUBLIC_NAMES = {
    "Affine2D",
    "Arc",
    "Assembly",
    "BSpline",
    "Circle",
    "Contour",
    "Dimension",
    "DimensionTextAttributeProperty",
    "DimensionTextFormatProperty",
    "Document",
    "Fillet",
    "Hatch",
    "HatchAssociation",
    "HatchPatternLine",
    "HatchPatternProperty",
    "InstancePathStep",
    "Leader",
    "LeaderPoint",
    "Line",
    "PartOccurrence",
    "PlacedGraphic",
    "Point",
    "ScanLimits",
    "Symbol",
    "Text",
    "draw",
    "detect_format",
    "read",
    "readfile",
    "scan",
    "scan_records",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    args = parser.parse_args()
    expected_version = args.version or version("ezmi2d")

    assert version("ezmi2d") == expected_version
    assert ezmi2d.__version__ == expected_version
    assert ezmi2d._core.core_version() == expected_version
    assert metadata("ezmi2d")["Requires-Python"] == ">=3.10"
    for name in PUBLIC_NAMES:
        assert hasattr(ezmi2d, name), name

    source = b"#~61\nP\n1\n1.25\n2.5\n|~\n##~~\n"
    raw = ezmi2d.scan(source)
    drawing = ezmi2d.read(source)
    point = drawing.entitydb[1]
    assert raw.termination == "file_marker"
    assert raw.source_view.readonly
    assert isinstance(point, ezmi2d.Point)
    assert point.location == ezmi2d.Vec2(1.25, 2.5)
    transform = ezmi2d.Affine2D(a=1.0, b=0.0, c=0.0, d=1.0, tx=3.0, ty=4.0)
    assert transform.transform_point(point.location) == ezmi2d.Vec2(4.25, 6.5)

    compressed = gzip.compress(source, mtime=0)
    packed = ezmi2d.read(compressed)
    assert packed.raw.format.compression == "gzip"
    assert packed.raw.container_bytes == compressed
    assert packed.raw.source_bytes == source
    assert packed.entitydb[1].location == point.location

    package = Path(ezmi2d.__file__).parent
    for relative in PACKAGE_FILES:
        assert (package / relative).is_file(), relative
    assert any(
        child.name.startswith("_core") and child.suffix in {".so", ".pyd"}
        for child in package.iterdir()
    )

    completed = subprocess.run(
        [sys.executable, "-m", "ezmi2d", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == f"ezmi2d {expected_version}"
    print(f"installed ezmi2d {expected_version} smoke passed on Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
