# Release process

The `release.yml` workflow builds one Python 3.10 stable-ABI wheel for each supported platform and
one source distribution:

| Artifact | Build target | Install verification |
|---|---|---|
| Linux x86-64 wheel | `x86_64-unknown-linux-gnu`, manylinux2014 | Ubuntu, Python 3.10 and 3.14 |
| Linux ARM64 wheel | `aarch64-unknown-linux-gnu`, manylinux2014 | `ubuntu-24.04-arm`, Python 3.10 |
| macOS universal2 wheel | `universal2-apple-darwin` | Apple Silicon macOS, Python 3.10 |
| Windows x64 wheel | `x86_64-pc-windows-msvc` | Windows, Python 3.10 |
| sdist | Cargo/maturin source archive | clean Ubuntu build/install on Python 3.10 |

All wheel installation jobs download the assembled artifacts and run without a source checkout.
The artifact inspector checks the `cp310-abi3` and portable platform tags, package metadata, typing
files, native extension, complete sdist development inputs, and exclusion of the separately
licensed external corpus. A `SHA256SUMS` file is generated after the set passes inspection.

## One-time PyPI configuration

Configure a PyPI Trusted Publisher for:

- owner/repository: `monozukuri-ai/ezmi`;
- workflow: `release.yml`;
- environment: `pypi`.

Configure the matching protected `pypi` GitHub environment; manual approval is recommended. Only
the tag-only publish job receives `id-token: write`. No long-lived PyPI token is used.

## Prepare a version

1. Update `project.version` in `pyproject.toml` and `workspace.package.version` in `Cargo.toml`.
2. Refresh and check locks with `cargo check --workspace` and `uv lock`, then run the gates below.
3. Update release-facing documentation and benchmark snapshots when behavior or performance changed.
4. Commit the reviewed release state and create the exact matching tag `v<version>`.

Local gates:

```console
uv sync --locked --extra dev
uv lock --check
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --locked
cargo install cargo-fuzz --version 0.13.2 --locked
uv run maturin develop --release --locked
uv run ruff format --check src tests benchmarks scripts/*.py
uv run ruff check src tests benchmarks scripts/*.py
uv run pytest -q
python scripts/check_release_version.py --tag v0.1.0
```

Build and inspect the native local wheel plus sdist before tagging:

```console
rm -rf dist
uv run maturin build --release --locked --out dist
uv run maturin sdist --out dist
python scripts/verify_release_artifacts.py \
  --dist dist --version 0.1.0 --expected-platform linux-x86_64 --require-sdist
```

Use the platform matching the local wheel when running the verifier. The release workflow passes all
four `--expected-platform` values.

## Workflow behavior

- `workflow_dispatch` performs the complete build and artifact verification as a non-publishing
  rehearsal.
- A pushed `v<version>` tag additionally checks that the version is not already present on PyPI.
- Publishing starts only after all platform install tests and the clean sdist install pass.
- PyPI upload uses Trusted Publishing; a GitHub release is created only after PyPI succeeds.
- A tag/version mismatch, duplicate PyPI version, missing platform, wrong ABI tag, missing package
  data, or unexpected external sample aborts the release.

PyPI files are immutable. If a tagged workflow fails after publishing, do not reuse the same version;
diagnose the failure and release a new version.
