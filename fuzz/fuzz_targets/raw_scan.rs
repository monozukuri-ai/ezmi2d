#![no_main]

use ezmi_core::{detect_format, scan, ScanOptions};
use libfuzzer_sys::fuzz_target;

const FUZZ_OPTIONS: ScanOptions = ScanOptions {
    max_file_size: 1024 * 1024,
    max_lines: 50_000,
    max_sections: 5_000,
    max_records: 20_000,
    max_line_size: 64 * 1024,
    max_record_size: 256 * 1024,
    max_decompressed_size: 1024 * 1024,
    max_compression_ratio: 100,
};

fuzz_target!(|data: &[u8]| {
    let _ = detect_format(data);
    let _ = scan(data, FUZZ_OPTIONS);
});
