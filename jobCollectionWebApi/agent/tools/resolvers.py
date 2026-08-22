"""Compatibility exports for the pre-market-domain resolver import path."""

from services.market.query_service import (
    MarketResolutionError,
    ResolvedDimension,
    resolve_city,
    resolve_industry,
    resolve_industry_codes,
)

ToolResolutionError = MarketResolutionError

__all__ = [
    "ResolvedDimension",
    "ToolResolutionError",
    "resolve_city",
    "resolve_industry",
    "resolve_industry_codes",
]
