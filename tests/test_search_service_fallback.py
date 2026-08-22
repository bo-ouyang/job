import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import ApiError, ConnectionTimeout


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services import search_service as search_module
from services.search_service import SearchService


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _api_error(status_code: int) -> ApiError:
    return ApiError(
        "Elasticsearch response failed",
        ApiResponseMeta(
            status_code,
            "1.1",
            HttpHeaders(),
            0.0,
            NodeConfig("http", "localhost", 9200),
        ),
        {},
    )


@pytest.mark.asyncio
async def test_search_falls_back_for_transport_failure_with_diagnostic_warning(monkeypatch):
    es = SimpleNamespace(search=AsyncMock(side_effect=ConnectionTimeout("timed out")))
    fallback_loader = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(search_module, "get_es", AsyncMock(return_value=es))
    monkeypatch.setattr(search_module.db_manager, "async_session", lambda: _SessionContext())
    monkeypatch.setattr(search_module.crud_job, "search", fallback_loader)

    result = await SearchService().search_jobs_with_meta(keyword="Python")

    assert result == (
        [],
        0,
        "postgresql",
        [
            "Elasticsearch 查询暂时不可用，已降级到 PostgreSQL",
            "search.es_fallback:ConnectionTimeout",
        ],
    )
    fallback_loader.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("invalid state"), KeyError("hits"), _api_error(400)],
    ids=["runtime", "missing_hits", "http_400"],
)
async def test_search_reraises_non_availability_failures_without_fallback(monkeypatch, failure):
    if isinstance(failure, KeyError):
        es = SimpleNamespace(search=AsyncMock(return_value={}))
        get_es = AsyncMock(return_value=es)
    else:
        get_es = AsyncMock(side_effect=failure)
    fallback_loader = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(search_module, "get_es", get_es)
    monkeypatch.setattr(search_module.db_manager, "async_session", lambda: _SessionContext())
    monkeypatch.setattr(search_module.crud_job, "search", fallback_loader)

    with pytest.raises(type(failure)):
        await SearchService().search_jobs_with_meta(keyword="Python")

    fallback_loader.assert_not_awaited()
