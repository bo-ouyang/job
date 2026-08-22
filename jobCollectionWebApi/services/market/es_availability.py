"""Elasticsearch availability classification shared by Market query adapters."""

from dataclasses import dataclass
from typing import Optional

from elasticsearch import ApiError, TransportError

from common.search.conn import ElasticsearchDisabledError


@dataclass(frozen=True)
class ElasticsearchFallback:
    """A failure that may safely use PostgreSQL as a degraded source."""

    reason: str

    def warning_code(self, operation: str) -> str:
        return f"{operation}.es_fallback:{self.reason}"


def classify_es_fallback(exc: Exception) -> Optional[ElasticsearchFallback]:
    """Return a fallback reason only for availability and retryable ES failures."""
    if isinstance(exc, ElasticsearchDisabledError):
        return ElasticsearchFallback(type(exc).__name__)
    if isinstance(exc, TransportError):
        return ElasticsearchFallback(type(exc).__name__)
    if isinstance(exc, ApiError):
        status_code = exc.status_code
        if status_code == 429 or 500 <= status_code <= 599:
            return ElasticsearchFallback(f"{type(exc).__name__}:{status_code}")
    return None
