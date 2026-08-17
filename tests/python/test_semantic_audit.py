from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[2]


def _load_audit_module() -> ModuleType:
    path = ROOT / "scripts" / "audit_semantics.py"
    spec = importlib.util.spec_from_file_location("audit_semantics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_semantic_audit_reports_raw_typed_and_evidence_fields() -> None:
    audit_module = _load_audit_module()
    report = audit_module.audit([ROOT / "tests" / "data" / "phase5.mi"])

    assert report["schema_version"] == 1
    assert report["totals"]["files"] == 1
    assert report["totals"]["raw_records"]["ASSE"] == 4
    assert report["totals"]["typed_entities"]["BSPL"] == 1
    assert report["totals"]["unsupported_entities"] == {}
    assert report["records"]["FIL"]["terminal_field_values"] == {"0": 1}
    assert report["arc_direction"]["FIL"]["orientation"] == {"0": 1}
    assert report["assembly"]["transform_values"] == {
        "(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)": 3,
        "(1.0, 0.0, 10.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)": 1,
    }
    assert report["bspline"]["definition_values"] == {"('0', '0')": 1}
    assert report["dimensions"]["types"] == {"DANG": 1}
    assert report["dimensions"]["unresolved_geometry"] == {"0": 1}
    assert report["dimensions"]["unresolved_points"] == {"0": 1}
    assert report["annotations"]["leader_vertex_counts"] == {"2": 1}
    assert report["annotations"]["hatch_boundary_counts"] == {"1": 1}
    assert report["annotations"]["hatch_pattern_present"] == {"True": 1}
    assert report["annotations"]["symbol_component_counts"] == {"3": 1}
    assert report["property_models"] == {
        "AssociatedStringsProperty": 1,
        "DimensionTextFormatProperty": 1,
        "HatchPatternProperty": 1,
        "PartStatusProperty": 1,
    }

    rendered = audit_module.markdown(report)
    assert "# ezmi2d semantic audit" in rendered
    assert "`BSPL`" in rendered
    assert "Graphic and annotation evidence" in rendered
