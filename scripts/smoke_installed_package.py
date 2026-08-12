#!/usr/bin/env python3
"""Exercise an installed ezmi distribution without importing the source tree."""

from __future__ import annotations

import argparse
import gzip
import subprocess
import sys
from importlib.metadata import metadata, version
from pathlib import Path

import ezmi

PACKAGE_FILES = {
    "__init__.py",
    "__main__.py",
    "_core.pyi",
    "diagnostics.py",
    "document.py",
    "entities.py",
    "raw.py",
    "py.typed",
}
PUBLIC_NAMES = {
    "Arc",
    "Assembly",
    "BSpline",
    "Circle",
    "Dimension",
    "Document",
    "Fillet",
    "Hatch",
    "Leader",
    "Line",
    "Point",
    "ScanLimits",
    "Symbol",
    "Text",
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
    expected_version = args.version or version("ezmi")

    assert version("ezmi") == expected_version
    assert ezmi.__version__ == expected_version
    assert ezmi._core.core_version() == expected_version
    assert metadata("ezmi")["Requires-Python"] == ">=3.10"
    for name in PUBLIC_NAMES:
        assert hasattr(ezmi, name), name

    source = b"#~61\nP\n1\n1.25\n2.5\n|~\n##~~\n"
    raw = ezmi.scan(source)
    drawing = ezmi.read(source)
    point = drawing.entitydb[1]
    assert raw.termination == "file_marker"
    assert raw.source_view.readonly
    assert isinstance(point, ezmi.Point)
    assert point.location == ezmi.Vec2(1.25, 2.5)

    compressed = gzip.compress(source, mtime=0)
    packed = ezmi.read(compressed)
    assert packed.raw.format.compression == "gzip"
    assert packed.raw.container_bytes == compressed
    assert packed.raw.source_bytes == source
    assert packed.entitydb[1].location == point.location

    package = Path(ezmi.__file__).parent
    for relative in PACKAGE_FILES:
        assert (package / relative).is_file(), relative
    assert any(
        child.name.startswith("_core") and child.suffix in {".so", ".pyd"}
        for child in package.iterdir()
    )

    completed = subprocess.run(
        [sys.executable, "-m", "ezmi", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == f"ezmi {expected_version}"
    print(f"installed ezmi {expected_version} smoke passed on Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
