"""Structured pricing-parser diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from llmcalc.models import ModelPricing

DiagnosticSeverity = Literal["info", "warning", "error"]
DiagnosticAction = Literal["skipped_entry", "ignored_field"]


@dataclass(frozen=True)
class PricingDiagnostic:
    model: str
    severity: DiagnosticSeverity
    code: str
    action: DiagnosticAction
    path: tuple[str | int, ...]
    message: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = list(self.path)
        return payload


@dataclass(frozen=True)
class PricingParseResult:
    models: dict[str, ModelPricing]
    diagnostics: tuple[PricingDiagnostic, ...]
