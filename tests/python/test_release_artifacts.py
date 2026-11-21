from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]


def _load_verify_module() -> ModuleType:
    path = ROOT / "scripts" / "verify_release_artifacts.py"
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("platform_tag", "expected"),
    [
        ("manylinux_2_17_x86_64.manylinux2014_x86_64", "linux-x86_64"),
        ("manylinux2014_x86_64.manylinux_2_17_x86_64", "linux-x86_64"),
        ("manylinux_2_17_aarch64.manylinux2014_aarch64", "linux-aarch64"),
        # The order of a compressed tag set differs between build tool releases.
        ("macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2", "macos-universal2"),
        ("macosx_10_12_universal2.macosx_10_12_x86_64.macosx_11_0_arm64", "macos-universal2"),
        ("macosx_10_12_universal2", "macos-universal2"),
        ("win_amd64", "windows-x86_64"),
    ],
)
def test_wheel_platform_is_read_from_every_tag(platform_tag: str, expected: str) -> None:
    verify = _load_verify_module()
    filename = f"ezmi2d-1.2.3-cp310-abi3-{platform_tag}.whl"

    assert verify._platform(filename, "1.2.3") == expected


@pytest.mark.parametrize(
    "platform_tag",
    [
        "linux_x86_64",
        "manylinux_2_17_x86_64.linux_x86_64",
        "manylinux_2_17_x86_64.manylinux_2_17_aarch64",
        "macosx_10_12_x86_64",
        "macosx_10_12_x86_64.macosx_11_0_arm64",
        "win32",
        "win_amd64.win32",
    ],
)
def test_wheel_with_a_non_portable_or_partial_platform_is_rejected(platform_tag: str) -> None:
    verify = _load_verify_module()
    filename = f"ezmi2d-1.2.3-cp310-abi3-{platform_tag}.whl"

    with pytest.raises(ValueError, match="unsupported or non-portable platform tag"):
        verify._platform(filename, "1.2.3")


def test_wheel_without_the_stable_abi_tag_is_rejected() -> None:
    verify = _load_verify_module()

    with pytest.raises(ValueError, match="cp310-abi3"):
        verify._platform("ezmi2d-1.2.3-cp312-cp312-win_amd64.whl", "1.2.3")
