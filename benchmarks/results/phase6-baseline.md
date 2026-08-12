# ezmi full-pipeline benchmark

Generated: `2026-08-12T14:53:32.318817+00:00`

This snapshot reports independent, non-additive measurements. `read_path_end_to_end` is the acceptance metric for the complete path from file I/O through decompression, scanning, semantic decoding, reference resolution, and Python object materialization.

## Conditions

- ezmi `0.1.0` on Python `3.13.1` (CPython)
- Platform: `Linux-6.8.0-136-generic-x86_64-with-glibc2.39` / `x86_64`
- Warmup runs: 1; timed runs: 5 per file and stage
- Corpus: 21 files, 1153163 container bytes, 1459462 logical bytes, 26035 records, 25922 addressable entities
- Garbage-collector cycles are disabled during each timed loop; normal reference-count cleanup still occurs outside the timed interval.

## Aggregate stages

| Stage | Scope | Sum of file medians (ms) | Throughput (MiB/s) |
|---|---|---:|---:|
| `read_container` | Path.read_bytes(); container I/O only | 0.189 | 5808.08 (container) |
| `detect_format_bytes` | ezmi.detect_format(bytes); signature/probe only | 0.118 | 6507.64 (probe) |
| `scan_bytes` | ezmi.scan(bytes); decompression, raw scan, and Python raw model | 1776.002 | 0.78 (logical) |
| `read_bytes` | ezmi.read(bytes); decompression, raw and semantic parse, Python model | 1976.608 | 0.70 (logical) |
| `read_path_end_to_end` | ezmi.read(path); I/O through complete semantic Python model | 1988.617 | 0.70 (logical) |

## Per-file full pipeline

| Input | Container / logical bytes | Records | Entities | Median (ms) |
|---|---:|---:|---:|---:|
| `samples/external/ptc-community-mandrel/compressed/am_2d_0.mi` | 87506 / 393805 | 4527 | 4499 | 452.103 |
| `samples/external/ptc-community-mandrel/mi/am_2d_0.mi` | 393805 / 393805 | 4527 | 4499 | 452.732 |
| `samples/external/takahiro-soarerdex/mi/F100` | 35603 / 35603 | 921 | 918 | 57.937 |
| `samples/external/takahiro-soarerdex/mi/F125` | 36201 / 36201 | 916 | 913 | 57.823 |
| `samples/external/takahiro-soarerdex/mi/F160` | 37463 / 37463 | 935 | 932 | 58.352 |
| `samples/external/takahiro-soarerdex/mi/F200` | 36392 / 36392 | 915 | 912 | 57.422 |
| `samples/external/takahiro-soarerdex/mi/F50` | 33408 / 33408 | 926 | 923 | 61.302 |
| `samples/external/takahiro-soarerdex/mi/F63` | 37441 / 37441 | 1017 | 1014 | 69.803 |
| `samples/external/takahiro-soarerdex/mi/F80` | 32677 / 32677 | 871 | 868 | 56.196 |
| `samples/external/takahiro-soarerdex/mi/S100` | 24295 / 24295 | 635 | 632 | 40.668 |
| `samples/external/takahiro-soarerdex/mi/S125` | 25499 / 25499 | 659 | 656 | 41.419 |
| `samples/external/takahiro-soarerdex/mi/S40` | 29593 / 29593 | 736 | 733 | 46.412 |
| `samples/external/takahiro-soarerdex/mi/S50` | 30196 / 30196 | 779 | 776 | 49.198 |
| `samples/external/takahiro-soarerdex/mi/S63` | 30390 / 30390 | 800 | 797 | 49.975 |
| `samples/external/takahiro-soarerdex/mi/S80` | 23175 / 23175 | 633 | 630 | 39.932 |
| `samples/external/takahiro-soarerdex/mi/T100` | 38932 / 38932 | 1032 | 1029 | 66.134 |
| `samples/external/takahiro-soarerdex/mi/T125` | 44633 / 44633 | 1034 | 1031 | 66.185 |
| `samples/external/takahiro-soarerdex/mi/T160` | 39620 / 39620 | 1046 | 1043 | 65.928 |
| `samples/external/takahiro-soarerdex/mi/T200` | 48582 / 48582 | 1035 | 1032 | 64.948 |
| `samples/external/takahiro-soarerdex/mi/T250` | 45612 / 45612 | 1051 | 1048 | 67.254 |
| `samples/external/takahiro-soarerdex/mi/T80` | 42140 / 42140 | 1040 | 1037 | 66.893 |

The paired JSON report contains SHA-256 input identities and every nanosecond sample. This is a development-machine snapshot, not a cross-machine performance guarantee.
