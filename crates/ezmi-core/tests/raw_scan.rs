use ezmi_core::{scan, FileTermination, RecordTermination, ScanOptions};

const MINIMAL_MI: &[u8] = include_bytes!("../../../tests/data/minimal.mi");

#[test]
fn scans_the_repository_fixture_without_losing_byte_ranges() {
    let document = scan(MINIMAL_MI, ScanOptions::default()).unwrap();

    assert_eq!(document.format.first_section, Some(2));
    assert_eq!(document.termination, FileTermination::FileMarker);
    assert_eq!(document.trailing_bytes, 0);
    assert_eq!(
        document
            .sections
            .iter()
            .map(|section| section.number)
            .collect::<Vec<_>>(),
        vec![2, 3, 41, 5, 6, 61, 62, 71, 72]
    );
    assert!(document.diagnostics.is_empty());

    let reconstructed = document
        .lines
        .iter()
        .flat_map(|line| {
            MINIMAL_MI[line.span.offset..line.span.end_offset()]
                .iter()
                .copied()
        })
        .collect::<Vec<_>>();
    assert_eq!(reconstructed, MINIMAL_MI);

    let point = document
        .records
        .iter()
        .find(|record| record.record_type.as_deref() == Some("P"))
        .unwrap();
    assert_eq!(point.termination, RecordTermination::EntityMarker);
    assert_eq!(
        &MINIMAL_MI[point.payload_span.offset..point.payload_span.end_offset()],
        b"P\n4\n0\n0\n"
    );

    let unknown = document
        .records
        .iter()
        .find(|record| record.record_type.as_deref() == Some("MYSTERY"))
        .unwrap();
    assert_eq!(unknown.section_number, 62);
}

#[test]
fn reports_data_after_the_first_file_terminator() {
    let data = b"#~2\n##~~\nextra\n";
    let document = scan(data, ScanOptions::default()).unwrap();

    assert_eq!(document.termination, FileTermination::FileMarker);
    assert_eq!(document.trailing_bytes, 6);
    assert_eq!(
        document
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code)
            .collect::<Vec<_>>(),
        vec!["MI_TRAILING_DATA"]
    );
}
