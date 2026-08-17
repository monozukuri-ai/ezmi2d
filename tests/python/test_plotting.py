from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import ezmi2d

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt  # noqa: E402

DATA = Path(__file__).parents[1] / "data"


def test_draw_renders_resolved_geometry_and_writes_png(tmp_path: Path) -> None:
    drawing = ezmi2d.read(DATA / "geometry.mi")

    axes = ezmi2d.draw(drawing, curve_segments=8, show_points=True)
    labels = {artist.get_label() for artist in axes.collections}
    assert labels == {"P", "LIN", "ARC", "CIR"}

    arc_collection = next(artist for artist in axes.collections if artist.get_label() == "ARC")
    arc_vertices = arc_collection.get_segments()[0]
    assert len(arc_vertices) == 9
    assert tuple(arc_vertices[0]) == pytest.approx((10.0, 5.0))
    assert tuple(arc_vertices[-1]) == pytest.approx((5.0, 10.0))
    assert axes.get_aspect() == 1.0

    output = tmp_path / "geometry.png"
    axes.figure.savefig(output)
    plt.close(axes.figure)
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_draw_samples_fillet_bspline_and_text() -> None:
    phase5 = ezmi2d.read(DATA / "phase5.mi")
    axes = ezmi2d.draw(phase5, curve_segments=16)
    assert {artist.get_label() for artist in axes.collections} == {"FIL", "BSPL"}
    plt.close(axes.figure)

    text_drawing = ezmi2d.read(DATA / "text-utf8.mi")
    axes = ezmi2d.draw(text_drawing)
    assert [artist.get_text() for artist in axes.texts] == ["日本語 café"]
    plt.close(axes.figure)


def test_draw_rejects_unverified_arc_orientation_without_guessing() -> None:
    drawing = ezmi2d.read(DATA / "geometry.mi")
    arc = drawing.query("ARC")[0]
    assert isinstance(arc, ezmi2d.Arc)
    altered = replace(arc, orientation=1, ccw=None)
    part = replace(drawing.parts[0], entities=(altered,))

    with pytest.warns(RuntimeWarning, match="unverified orientation"):
        axes = ezmi2d.draw(part)
    assert len(axes.collections) == 0
    plt.close(axes.figure)


def test_draw_can_expand_shared_assembly_instances() -> None:
    drawing = ezmi2d.read(DATA / "phase5.mi")
    axes = ezmi2d.draw(drawing, curve_segments=8, expand_instances=True)

    fillets = next(artist for artist in axes.collections if artist.get_label() == "FIL")
    assert len(fillets.get_segments()) == 2
    assert tuple(fillets.get_segments()[0][0]) == pytest.approx((1.0, 0.0))
    assert tuple(fillets.get_segments()[1][0]) == pytest.approx((11.0, 0.0))
    plt.close(axes.figure)


@pytest.mark.parametrize("curve_segments", [0, 1])
def test_draw_validates_curve_resolution(curve_segments: int) -> None:
    drawing = ezmi2d.read(DATA / "geometry.mi")
    with pytest.raises(ValueError, match="at least 2"):
        ezmi2d.draw(drawing, curve_segments=curve_segments)
