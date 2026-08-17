#!/usr/bin/env python3
"""Verify ezmi2d wheel/sdist names, metadata, contents, and platform coverage."""

from __future__ import annotations

import argparse
import email.parser
import tarfile
import zipfile
from pathlib import Path

PLATFORMS = {
    "linux-x86_64",
    "linux-aarch64",
    "macos-universal2",
    "windows-x86_64",
}
WHEEL_PACKAGE_FILES = {
    "ezmi2d/__init__.py",
    "ezmi2d/__main__.py",
    "ezmi2d/_core.pyi",
    "ezmi2d/diagnostics.py",
    "ezmi2d/document.py",
    "ezmi2d/entities.py",
    "ezmi2d/plotting.py",
    "ezmi2d/raw.py",
    "ezmi2d/py.typed",
}
SDIST_FILES = {
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "benchmarks/README.md",
    "benchmarks/benchmark_pipeline.py",
    "benchmarks/results/phase6-baseline.json",
    "benchmarks/results/phase6-baseline.md",
    "docs/api.md",
    "docs/mi-format-research.md",
    "docs/releasing.md",
    "examples/plot_mi.py",
    "fuzz/Cargo.lock",
    "fuzz/Cargo.toml",
    "fuzz/fuzz_targets/raw_scan.rs",
    "fuzz/fuzz_targets/semantic_read.rs",
    "samples/README.md",
    "samples/manifest.toml",
    "scripts/check_release_version.py",
    "scripts/audit_semantics.py",
    "scripts/fetch_external_samples.sh",
    "scripts/smoke_installed_package.py",
    "scripts/verify_release_artifacts.py",
    "tests/data/geometry.mi",
    "tests/data/minimal.mi",
    "tests/data/phase5.mi",
    "tests/data/text-utf8.mi",
    "tests/python/test_semantic_audit.py",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--expected-platform",
        action="append",
        choices=sorted(PLATFORMS),
        required=True,
    )
    parser.add_argument("--require-sdist", action="store_true")
    parser.add_argument("--require-manylinux2014", action="store_true")
    return parser


def _platform(filename: str, version: str) -> str:
    prefix = f"ezmi2d-{version}-cp310-abi3-"
    if not filename.startswith(prefix) or not filename.endswith(".whl"):
        raise ValueError(f"wheel does not use the required cp310-abi3 tag: {filename}")
    tag = filename[len(prefix) : -4]
    if "manylinux" in tag and tag.endswith("x86_64"):
        return "linux-x86_64"
    if "manylinux" in tag and tag.endswith("aarch64"):
        return "linux-aarch64"
    if tag.startswith("macosx_") and tag.endswith("universal2"):
        return "macos-universal2"
    if tag == "win_amd64":
        return "windows-x86_64"
    raise ValueError(f"wheel has an unsupported or non-portable platform tag: {filename}")


def _metadata(archive: zipfile.ZipFile, filename: str) -> email.message.Message:
    matches = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    if len(matches) != 1:
        raise ValueError(f"{filename}: expected one METADATA file, found {len(matches)}")
    parser = email.parser.BytesParser()
    return parser.parsebytes(archive.read(matches[0]))


def _verify_wheel(path: Path, version: str, *, require_manylinux2014: bool) -> str:
    platform_name = _platform(path.name, version)
    if require_manylinux2014 and platform_name.startswith("linux-"):
        platform_tag = path.name.removesuffix(".whl").rsplit("-", maxsplit=1)[-1]
        if "manylinux_2_17_" not in platform_tag and "manylinux2014_" not in platform_tag:
            raise ValueError(f"{path.name}: Linux release wheel is not manylinux2014-compatible")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = WHEEL_PACKAGE_FILES - names
        if missing:
            raise ValueError(f"{path.name}: missing package files: {sorted(missing)}")
        extension_suffix = ".pyd" if platform_name == "windows-x86_64" else ".so"
        if not any(
            name.startswith("ezmi2d/_core") and name.endswith(extension_suffix) for name in names
        ):
            raise ValueError(f"{path.name}: native extension {extension_suffix} is missing")
        if any("samples/external/" in name for name in names):
            raise ValueError(f"{path.name}: external corpus data must not be distributed")
        metadata = _metadata(archive, path.name)
        if metadata["Name"] != "ezmi2d":
            raise ValueError(f"{path.name}: unexpected Name metadata {metadata['Name']!r}")
        if metadata["Version"] != version:
            raise ValueError(f"{path.name}: unexpected Version metadata {metadata['Version']!r}")
        if metadata["Requires-Python"] != ">=3.10":
            raise ValueError(
                f"{path.name}: unexpected Requires-Python {metadata['Requires-Python']!r}"
            )
    return platform_name


def _verify_sdist(path: Path, version: str) -> None:
    expected_prefix = f"ezmi2d-{version}/"
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
    if any("/samples/external/" in name for name in names):
        raise ValueError(f"{path.name}: external corpus data must not be distributed")
    relative_names = {
        name[len(expected_prefix) :]
        for name in names
        if name.startswith(expected_prefix) and name != expected_prefix.rstrip("/")
    }
    missing = SDIST_FILES - relative_names
    if missing:
        raise ValueError(f"{path.name}: missing source files: {sorted(missing)}")


def main() -> int:
    args = _parser().parse_args()
    wheels = sorted(args.dist.glob("*.whl"))
    expected = set(args.expected_platform)
    if len(wheels) != len(expected):
        raise RuntimeError(f"expected {len(expected)} wheel(s), found {len(wheels)}")
    actual: set[str] = set()
    for wheel in wheels:
        platform_name = _verify_wheel(
            wheel,
            args.version,
            require_manylinux2014=args.require_manylinux2014,
        )
        if platform_name in actual:
            raise RuntimeError(f"duplicate wheel platform: {platform_name}")
        actual.add(platform_name)
    if actual != expected:
        raise RuntimeError(
            f"wheel platforms differ: expected {sorted(expected)}, got {sorted(actual)}"
        )

    sdists = sorted(args.dist.glob("*.tar.gz"))
    if args.require_sdist:
        if len(sdists) != 1:
            raise RuntimeError(f"expected one sdist, found {len(sdists)}")
        expected_name = f"ezmi2d-{args.version}.tar.gz"
        if sdists[0].name != expected_name:
            raise RuntimeError(f"unexpected sdist name: {sdists[0].name}")
        _verify_sdist(sdists[0], args.version)
    elif sdists:
        raise RuntimeError("sdist present without --require-sdist")

    print(
        f"verified ezmi2d {args.version}: {len(wheels)} wheel(s) for "
        f"{', '.join(sorted(actual))}" + (" and one sdist" if args.require_sdist else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
