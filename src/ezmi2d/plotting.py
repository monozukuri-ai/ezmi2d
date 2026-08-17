"""Matplotlib-based diagnostic previews for decoded MI geometry.

The renderer intentionally visualizes the verified semantic geometry rather
than attempting to reproduce MI display attributes whose meanings are not yet
known.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .document import Document, Part
from .entities import Arc, BSpline, Circle, Graphic, Line, Text

if TYPE_CHECKING:
    from matplotlib.axes import Axes


DEFAULT_COLORS: Mapping[str, str] = {
    "LIN": "#1f2937",
    "ARC": "#2563eb",
    "FIL": "#d97706",
    "BSPL": "#dc2626",
    "CIR": "#059669",
    "TEX": "#7c3aed",
    "P": "#db2777",
}

_GEOMETRY_ORDER = ("LIN", "ARC", "FIL", "BSPL", "CIR")


def draw(
    source: Document | Part,
    *,
    ax: Axes | None = None,
    curve_segments: int = 128,
    show_points: bool = False,
    show_text: bool = True,
    colors: Mapping[str, str] | None = None,
    line_width: float = 0.8,
    point_size: float = 8.0,
    text_font_size: float = 8.0,
    text_font_family: str | None = None,
    warn_on_skipped: bool = True,
) -> Axes:
    """Draw decoded geometry from a document or part on a Matplotlib axes.

    Passing a :class:`~ezmi2d.Document` draws every directly decoded part
    definition once. Assembly instance transforms are deliberately not applied
    because their matrix convention is not yet part of ezmi2d's verified public
    contract. Pass a :class:`~ezmi2d.Part` to inspect one definition in isolation.

    Arc orientation ``0`` is rendered counter-clockwise, matching every paired
    MI/DXF sample in the current corpus. Other orientation values are skipped
    with a warning instead of being guessed.
    """

    if not isinstance(source, (Document, Part)):
        raise TypeError("source must be an ezmi2d.Document or ezmi2d.Part")
    if not isinstance(curve_segments, int) or isinstance(curve_segments, bool):
        raise TypeError("curve_segments must be an integer")
    if curve_segments < 2:
        raise ValueError("curve_segments must be at least 2")
    _require_positive_finite("line_width", line_width)
    _require_positive_finite("point_size", point_size)
    _require_positive_finite("text_font_size", text_font_size)

    pyplot, line_collection_type = _load_matplotlib()
    if ax is None:
        _, ax = pyplot.subplots()

    palette = dict(DEFAULT_COLORS)
    if colors is not None:
        palette.update(colors)

    polylines: dict[str, list[list[tuple[float, float]]]] = {kind: [] for kind in _GEOMETRY_ORDER}
    unresolved_ids: list[int] = []
    unknown_orientation_ids: list[int] = []

    for entity in source.entities:
        if isinstance(entity, Text):
            continue
        if isinstance(entity, Arc) and entity.orientation != 0:
            unknown_orientation_ids.append(entity.id)
            continue
        vertices = _entity_vertices(entity, curve_segments)
        if vertices is None:
            unresolved_ids.append(entity.id)
            continue
        polylines[entity.mi_type].append(vertices)

    for kind in _GEOMETRY_ORDER:
        paths = polylines[kind]
        if not paths:
            continue
        collection = line_collection_type(
            paths,
            colors=palette[kind],
            linewidths=line_width,
            label=kind,
            zorder=2,
        )
        ax.add_collection(collection)

    if show_points and source.points:
        ax.scatter(
            [point.location.x for point in source.points],
            [point.location.y for point in source.points],
            color=palette["P"],
            label="P",
            marker=".",
            s=point_size,
            zorder=3,
        )

    undecoded_text_ids: list[int] = []
    if show_text:
        font_options = {} if text_font_family is None else {"fontfamily": text_font_family}
        for entity in source.texts:
            if entity.text is None:
                undecoded_text_ids.append(entity.id)
                continue
            # The paired DXF corpus validates the baseline insertion point as
            # half a text height below the serialized MI origin.
            x = entity.origin.x
            y = entity.origin.y - entity.height / 2.0
            ax.text(
                x,
                y,
                entity.text,
                color=palette["TEX"],
                fontsize=text_font_size,
                verticalalignment="baseline",
                zorder=4,
                **font_options,
            )
            ax.update_datalim([(x, y)])

    ax.autoscale_view()
    ax.margins(0.05)
    ax.set_aspect("equal", adjustable="box")

    if warn_on_skipped:
        _warn_about_skipped(
            unresolved_ids=unresolved_ids,
            unknown_orientation_ids=unknown_orientation_ids,
            undecoded_text_ids=undecoded_text_ids,
        )
    return ax


def _entity_vertices(entity: Graphic, curve_segments: int) -> list[tuple[float, float]] | None:
    if isinstance(entity, Line):
        if entity.start is None or entity.end is None:
            return None
        return [(entity.start.x, entity.start.y), (entity.end.x, entity.end.y)]

    if isinstance(entity, Arc):
        if (
            entity.center is None
            or entity.start is None
            or entity.end is None
            or entity.radius is None
            or entity.start_angle is None
            or entity.end_angle is None
        ):
            return None
        sweep = (entity.end_angle - entity.start_angle) % math.tau
        if math.isclose(sweep, 0.0, abs_tol=1e-12):
            sweep = math.tau
        vertices = [
            (
                entity.center.x
                + entity.radius * math.cos(entity.start_angle + sweep * index / curve_segments),
                entity.center.y
                + entity.radius * math.sin(entity.start_angle + sweep * index / curve_segments),
            )
            for index in range(curve_segments + 1)
        ]
        vertices[0] = (entity.start.x, entity.start.y)
        vertices[-1] = (entity.end.x, entity.end.y)
        return vertices

    if isinstance(entity, BSpline):
        start, end = entity.parameter_domain
        try:
            points = [
                entity.evaluate(start + (end - start) * index / curve_segments)
                for index in range(curve_segments + 1)
            ]
        except (LookupError, ValueError):
            return None
        return [(point.x, point.y) for point in points]

    if isinstance(entity, Circle):
        if entity.center is None or entity.radius is None:
            return None
        return [
            (
                entity.center.x + entity.radius * math.cos(math.tau * index / curve_segments),
                entity.center.y + entity.radius * math.sin(math.tau * index / curve_segments),
            )
            for index in range(curve_segments + 1)
        ]

    return None


def _require_positive_finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite")


def _load_matplotlib() -> tuple[Any, Any]:
    try:
        from matplotlib import pyplot
        from matplotlib.collections import LineCollection
    except ImportError as error:  # pragma: no cover - depends on caller environment
        raise ImportError(
            "Matplotlib plotting support is unavailable; install ezmi2d with "
            "`pip install 'ezmi2d[plot]'`"
        ) from error
    return pyplot, LineCollection


def _warn_about_skipped(
    *,
    unresolved_ids: list[int],
    unknown_orientation_ids: list[int],
    undecoded_text_ids: list[int],
) -> None:
    if unknown_orientation_ids:
        warnings.warn(
            "skipped ARC/FIL entities with an unverified orientation value: "
            f"{_summarize_ids(unknown_orientation_ids)}",
            RuntimeWarning,
            stacklevel=3,
        )
    if unresolved_ids:
        warnings.warn(
            f"skipped graphic entities with unresolved geometry: {_summarize_ids(unresolved_ids)}",
            RuntimeWarning,
            stacklevel=3,
        )
    if undecoded_text_ids:
        warnings.warn(
            "skipped text entities whose bytes could not be decoded strictly: "
            f"{_summarize_ids(undecoded_text_ids)}",
            RuntimeWarning,
            stacklevel=3,
        )


def _summarize_ids(entity_ids: list[int]) -> str:
    shown = ", ".join(str(entity_id) for entity_id in entity_ids[:10])
    if len(entity_ids) <= 10:
        return shown
    return f"{shown}, ... ({len(entity_ids)} total)"


__all__ = ["DEFAULT_COLORS", "draw"]
