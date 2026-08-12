# Benchmarks

`benchmark_pipeline.py` measures each public reader boundary separately and writes the same run as
machine-readable JSON and a compact Markdown report. The stages are intentionally independent and
must not be added together. `read_path_end_to_end` is the complete processing path: file I/O,
optional decompression, raw scanning, semantic decoding, reference resolution, and Python object
materialization.

Run a repository-fixture smoke benchmark:

```console
uv run python benchmarks/benchmark_pipeline.py tests/data \
  --warmup 1 --repeat 5 \
  --json-output /tmp/ezmi-benchmark.json \
  --markdown-output /tmp/ezmi-benchmark.md
```

Reproduce the Phase 6 corpus snapshot after fetching the opt-in external samples:

```console
./scripts/fetch_external_samples.sh
uv run python benchmarks/benchmark_pipeline.py \
  samples/external/takahiro-soarerdex/mi \
  samples/external/ptc-community-mandrel/compressed \
  samples/external/ptc-community-mandrel/mi \
  --warmup 1 --repeat 5 \
  --json-output benchmarks/results/phase6-baseline.json \
  --markdown-output benchmarks/results/phase6-baseline.md
```

Results are machine-specific snapshots. Compare runs made on the same host and power/performance
configuration. JSON input entries include SHA-256 identities so corpus drift is visible.
