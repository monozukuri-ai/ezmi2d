use std::io::Write;

use ezmi2d_core::{read_with_encoding, scan, ScanOptions};
use flate2::write::GzEncoder;
use flate2::Compression;

const MINIMAL_MI: &[u8] = include_bytes!("../../../tests/data/minimal.mi");
const GEOMETRY_MI: &[u8] = include_bytes!("../../../tests/data/geometry.mi");
const TEXT_MI: &[u8] = include_bytes!("../../../tests/data/text-utf8.mi");
const PHASE5_MI: &[u8] = include_bytes!("../../../tests/data/phase5.mi");

fn bounded_options() -> ScanOptions {
    ScanOptions {
        max_file_size: 1024 * 1024,
        max_lines: 50_000,
        max_sections: 5_000,
        max_records: 20_000,
        max_line_size: 64 * 1024,
        max_record_size: 256 * 1024,
        max_decompressed_size: 1024 * 1024,
        max_compression_ratio: 100,
    }
}

fn exercise(data: &[u8]) {
    let _ = scan(data, bounded_options());
    let _ = read_with_encoding(data, bounded_options(), None);
}

fn gzip(data: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

#[test]
fn every_fixture_truncation_is_handled_without_panicking() {
    for fixture in [MINIMAL_MI, GEOMETRY_MI, TEXT_MI, PHASE5_MI] {
        for end in 0..=fixture.len() {
            exercise(&fixture[..end]);
        }
    }
}

#[test]
fn deterministic_fixture_mutations_are_handled_without_panicking() {
    for fixture in [MINIMAL_MI, GEOMETRY_MI, TEXT_MI, PHASE5_MI] {
        let sample_count = fixture.len().min(256);
        for sample in 0..sample_count {
            let index = sample * fixture.len() / sample_count;
            for mask in [0x01, 0x80, 0xff] {
                let mut mutated = fixture.to_vec();
                mutated[index] ^= mask;
                exercise(&mutated);
            }
        }
    }
}

#[test]
fn truncated_and_mutated_gzip_envelopes_are_handled_without_panicking() {
    let compressed = gzip(PHASE5_MI);
    for end in 0..=compressed.len() {
        exercise(&compressed[..end]);
    }
    for index in 0..compressed.len() {
        let mut mutated = compressed.clone();
        mutated[index] ^= 0xff;
        exercise(&mutated);
    }
}

#[test]
fn bspline_layout_search_is_bounded_to_the_documented_prefix() {
    let mut data = b"#~61\nBSPL\n1\n".to_vec();
    for _ in 0..128 {
        data.extend_from_slice(b"0\n");
    }
    data.extend_from_slice(b"|~\n##~~\n");

    let document = read_with_encoding(&data, bounded_options(), None).unwrap();
    assert!(document
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "MI_INVALID_ENTITY_RECORD"));
}
