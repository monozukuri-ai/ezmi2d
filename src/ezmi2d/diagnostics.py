"""Stable source locations and non-fatal parser diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DiagnosticSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open byte range and its one-based source line range."""

    offset: int
    length: int
    start_line: int
    end_line: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One stable, source-located observation from a lossless scan."""

    severity: DiagnosticSeverity
    code: str
    message: str
    span: SourceSpan
    action: str | None = None
