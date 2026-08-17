use ezmi2d_core::{read, EncodingSource, ScanOptions, SemanticEntity, TextEncoding};

const GEOMETRY_MI: &[u8] = include_bytes!("../../../tests/data/geometry.mi");
const PHASE5_MI: &[u8] = include_bytes!("../../../tests/data/phase5.mi");
const UNKNOWN_RECORD: &[u8] = b"MYSTERY\n13\nopaque\n|~";
const SHIFT_JIS_TEXT_RECORD: &[u8] = b"TEX\n13\n3\n0\n1\n1\n2\n4\n1\n0\n25\n0\n1\n12\n0\n0\n1\n0\n0\nhp_i3098_v\n0\n0\n3.5\n3.5\n0\n1.5\n0\n1\n\x93\xfa\x96\x7b\x8c\xea\n0\n|~";

#[test]
fn decodes_the_verified_legacy_geometry_subset() {
    let document = read(GEOMETRY_MI, ScanOptions::default()).unwrap();

    let global = document.global.as_ref().unwrap();
    assert_eq!(global.version.as_deref(), Some("2.10"));
    assert_eq!(global.unit.as_deref(), Some("mm"));
    assert_eq!(global.extents.as_ref().unwrap().min.x, 0.0);
    assert_eq!(global.extents.as_ref().unwrap().max.y, 10.0);
    assert_eq!(document.toc_last_entity, Some(13));

    assert_eq!(document.parts.len(), 1);
    assert_eq!(document.top_part_index, Some(0));
    assert_eq!(document.parts[0].name.text.as_deref(), Some("Top"));
    assert_eq!(document.parts[0].point_ids, vec![4, 5, 6, 7, 8, 9]);
    assert_eq!(document.parts[0].graphic_entity_ids, vec![10, 11, 12]);
    assert_eq!(document.parts[0].unsupported_entity_ids, vec![13]);

    let SemanticEntity::Line(line) = document.entity(10).unwrap() else {
        panic!("entity 10 is not a line")
    };
    assert_eq!(line.start.as_ref().unwrap().x, 0.0);
    assert_eq!(line.end.as_ref().unwrap().x, 10.0);
    assert_eq!(line.graphic.property_id, Some(2));

    let SemanticEntity::Arc(arc) = document.entity(11).unwrap() else {
        panic!("entity 11 is not an arc")
    };
    assert_eq!(arc.radius(), Some(5.0));
    assert_eq!(arc.start_angle(), Some(0.0));
    assert_eq!(arc.end_angle(), Some(std::f64::consts::FRAC_PI_2));

    let SemanticEntity::Circle(circle) = document.entity(12).unwrap() else {
        panic!("entity 12 is not a circle")
    };
    assert_eq!(circle.radius(), Some(3.0));

    assert_eq!(
        document
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.code)
            .collect::<Vec<_>>(),
        vec!["MI_UNSUPPORTED_ENTITY"]
    );
}

#[test]
fn normalizes_angles_to_one_positive_turn() {
    let center = ezmi2d_core::Point2::new(0.0, 0.0);
    let below = ezmi2d_core::Point2::new(1.0, -1.0);

    let angle = center.angle_to(&below);
    assert!(angle > std::f64::consts::PI);
    assert!(angle < std::f64::consts::TAU);
}

#[test]
fn decodes_declared_shift_jis_tex_as_a_typed_entity() {
    let mut data = b"#~1\nENCODING:SJIS\n".to_vec();
    data.extend(replace_once(
        GEOMETRY_MI,
        UNKNOWN_RECORD,
        SHIFT_JIS_TEXT_RECORD,
    ));

    let document = read(&data, ScanOptions::default()).unwrap();
    assert_eq!(document.encoding.encoding, Some(TextEncoding::ShiftJis));
    assert_eq!(document.encoding.source, EncodingSource::Declared);
    assert_eq!(document.encoding.declared_name.as_deref(), Some("SJIS"));
    assert_eq!(document.parts[0].graphic_entity_ids, vec![10, 11, 12, 13]);
    assert!(document.parts[0].unsupported_entity_ids.is_empty());

    let SemanticEntity::Text(text) = document.entity(13).unwrap() else {
        panic!("entity 13 is not text")
    };
    assert_eq!(text.content.text.as_deref(), Some("日本語"));
    assert_eq!(text.content.bytes, b"\x93\xfa\x96\x7b\x8c\xea");
    assert_eq!(text.content.encoding, Some(TextEncoding::ShiftJis));
    assert_eq!(text.font_name.text.as_deref(), Some("hp_i3098_v"));
    assert_eq!(text.origin().x, 25.0);
    assert_eq!(text.origin().y, 12.0);
    assert_eq!(text.height(), 3.5);
    assert!(document.diagnostics.is_empty());
}

#[test]
fn decodes_phase5_curves_annotations_and_part_structure() {
    let document = read(PHASE5_MI, ScanOptions::default()).unwrap();

    let SemanticEntity::Fillet(fillet) = document.entity(20).unwrap() else {
        panic!("entity 20 is not a fillet")
    };
    assert_eq!(fillet.radius(), Some(1.0));

    let SemanticEntity::BSpline(spline) = document.entity(21).unwrap() else {
        panic!("entity 21 is not a B-spline")
    };
    assert_eq!(spline.order, 4);
    assert_eq!(spline.degree(), 3);
    assert_eq!(spline.parameter_domain(), Some((0.0, 1.0)));
    assert_eq!(
        spline.evaluate(0.5),
        Some(ezmi2d_core::Point2::new(0.5, 0.75))
    );
    assert_eq!(spline.samples.len(), 2);

    assert!(matches!(
        document.entity(30),
        Some(SemanticEntity::DimensionTolerance(_))
    ));
    assert!(matches!(
        document.entity(31),
        Some(SemanticEntity::Dimension(_))
    ));
    assert!(matches!(
        document.entity(32),
        Some(SemanticEntity::Leader(_))
    ));
    assert!(matches!(
        document.entity(33),
        Some(SemanticEntity::Hatch(_))
    ));
    assert!(matches!(
        document.entity(34),
        Some(SemanticEntity::Symbol(_))
    ));

    assert_eq!(document.top_part_index, Some(3));
    assert_eq!(document.root_part_indices, vec![3]);
    assert_eq!(document.sheet_part_indices, vec![1, 2]);
    assert_eq!(document.parts[0].parent_part_indices, vec![1, 2]);
    assert_eq!(document.parts[3].child_part_indices, vec![1, 2]);
    let SemanticEntity::Assembly(root) = document.entity(6).unwrap() else {
        panic!("entity 6 is not an assembly")
    };
    assert_eq!(root.instances.len(), 2);
    assert!(root.instances.iter().all(|instance| instance.is_sheet));
    assert_eq!(root.instances[1].target_part_index, Some(2));
}

fn replace_once(input: &[u8], old: &[u8], new: &[u8]) -> Vec<u8> {
    let offset = input
        .windows(old.len())
        .position(|window| window == old)
        .expect("fixture marker is present");
    let mut result = Vec::with_capacity(input.len() - old.len() + new.len());
    result.extend_from_slice(&input[..offset]);
    result.extend_from_slice(new);
    result.extend_from_slice(&input[offset + old.len()..]);
    result
}
