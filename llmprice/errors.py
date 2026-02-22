"""Typed exceptions for llmprice."""


class PricingError(Exception):
    """Base pricing error type."""


class PricingFetchError(PricingError):
    """Raised when pricing data cannot be fetched and no cache is usable."""


class PricingSchemaError(PricingError):
    """Raised when upstream pricing data is invalid."""
