"""Typed exceptions for llmcalc."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmcalc.diagnostics import PricingDiagnostic


class PricingError(Exception):
    """Base pricing error type."""


class PricingFetchError(PricingError):
    """Raised when pricing data cannot be fetched and no cache is usable."""


class PricingSchemaError(PricingError):
    """Raised when upstream pricing data is invalid."""

    def __init__(
        self,
        message: str,
        diagnostics: tuple[PricingDiagnostic, ...] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class PricingHistoryError(PricingError):
    """Raised when a historical LiteLLM snapshot cannot be resolved or fetched."""
