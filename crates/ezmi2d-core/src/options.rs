/// Maximum number of bytes accepted for one complete input (1 GiB).
pub const DEFAULT_MAX_FILE_SIZE_BYTES: usize = 1024 * 1024 * 1024;

/// Maximum number of physical lines in one input.
pub const DEFAULT_MAX_LINES: usize = 10_000_000;

/// Maximum number of MI sections in one input.
pub const DEFAULT_MAX_SECTIONS: usize = 100_000;

/// Maximum number of framed and unframed logical records in one input.
pub const DEFAULT_MAX_RECORDS: usize = 5_000_000;

/// Maximum content length of one physical line (16 MiB).
pub const DEFAULT_MAX_LINE_SIZE_BYTES: usize = 16 * 1024 * 1024;

/// Maximum complete size of one logical record (256 MiB).
pub const DEFAULT_MAX_RECORD_SIZE_BYTES: usize = 256 * 1024 * 1024;

/// Maximum number of bytes accepted after decompressing one MI stream (1 GiB).
pub const DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES: usize = 1024 * 1024 * 1024;

/// Maximum permitted decompressed/compressed size ratio.
pub const DEFAULT_MAX_COMPRESSION_RATIO: usize = 1_000;

/// Limits applied by the lossless MI scanner.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ScanOptions {
    pub max_file_size: usize,
    pub max_lines: usize,
    pub max_sections: usize,
    pub max_records: usize,
    pub max_line_size: usize,
    pub max_record_size: usize,
    pub max_decompressed_size: usize,
    pub max_compression_ratio: usize,
}

impl Default for ScanOptions {
    fn default() -> Self {
        Self {
            max_file_size: DEFAULT_MAX_FILE_SIZE_BYTES,
            max_lines: DEFAULT_MAX_LINES,
            max_sections: DEFAULT_MAX_SECTIONS,
            max_records: DEFAULT_MAX_RECORDS,
            max_line_size: DEFAULT_MAX_LINE_SIZE_BYTES,
            max_record_size: DEFAULT_MAX_RECORD_SIZE_BYTES,
            max_decompressed_size: DEFAULT_MAX_DECOMPRESSED_SIZE_BYTES,
            max_compression_ratio: DEFAULT_MAX_COMPRESSION_RATIO,
        }
    }
}
