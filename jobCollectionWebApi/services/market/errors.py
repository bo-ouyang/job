"""Lightweight market-domain exceptions shared by dependency-sensitive layers."""


class MarketResolutionError(ValueError):
    """Raised when a market dimension is empty, unknown, or ambiguous."""
