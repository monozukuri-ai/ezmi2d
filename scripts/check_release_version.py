#!/usr/bin/env python3
"""Validate Python/Rust release versions and an optional release tag."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import tomllib


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="expected v<version> Git tag")
    parser.add_argument("--check-pypi", action="store_true")
    parser.add_argument("--github-output", type=Path)
    return parser


def _load_version(path: Path, *keys: str) -> str:
    value: object = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in keys:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: {'.'.join(keys)} is not a table path")
        value = value[key]
    if not isinstance(value, str):
        raise ValueError(f"{path}: {'.'.join(keys)} is not a string")
    return value


def _ensure_unpublished(package: str, version: str) -> None:
    package_path = urllib.parse.quote(package, safe="")
    version_path = urllib.parse.quote(version, safe="")
    url = f"https://pypi.org/pypi/{package_path}/{version_path}/json"
    try:
        with urllib.request.urlopen(url, timeout=30):
            pass
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return
        raise
    raise RuntimeError(
        f"{package} {version} is already published on PyPI; published files cannot be replaced"
    )


def main() -> int:
    args = _parser().parse_args()
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package = pyproject["project"]["name"]
    python_version = _load_version(Path("pyproject.toml"), "project", "version")
    rust_version = _load_version(Path("Cargo.toml"), "workspace", "package", "version")
    if python_version != rust_version:
        raise RuntimeError(
            f"version mismatch: pyproject.toml={python_version}, Cargo.toml={rust_version}"
        )
    if args.tag is not None and args.tag != f"v{python_version}":
        raise RuntimeError(f"tag/version mismatch: expected v{python_version}, got {args.tag}")
    if args.check_pypi:
        _ensure_unpublished(package, python_version)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            print(f"version={python_version}", file=output)
    print(python_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
