import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import ApiError, ConnectionTimeout


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services.market import query_service as query_module
from services.market.query_service import MarketQueryService


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
async def test_faceted_stats_falls_back_for_es_connection_timeout_with_traceable_warning(
    monkeypatch,
):
    statistics_service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=ConnectionTimeout("timed out"))
    )
    fallback_loader = AsyncMock(return_value={"total_jobs": 2})
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", fallback_loader)

    snapshot = await MarketQueryService(statistics_service=statistics_service).get_faceted_stats(
        object(),
        keyword="Python",
    )

    assert snapshot.data == {"total_jobs": 2}
    assert snapshot.source == "postgresql"
    assert snapshot.warnings == ["Elasticsearch 查询暂时不可用，已降级到 PostgreSQL"]
    assert snapshot.warning_codes == ["market.stats.es_fallback:ConnectionTimeout"]
    fallback_loader.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_faceted_stats_falls_back_for_retryable_es_http_errors(monkeypatch, status_code):
    statistics_service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=_api_error(status_code))
    )
    fallback_loader = AsyncMock(return_value={"total_jobs": 2})
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", fallback_loader)

    snapshot = await MarketQueryService(statistics_service=statistics_service).get_faceted_stats(
        object()
    )

    assert snapshot.source == "postgresql"
    assert snapshot.warning_codes == [f"market.stats.es_fallback:ApiError:{status_code}"]
    fallback_loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_faceted_stats_reraises_programming_errors_without_postgresql_fallback(monkeypatch):
    statistics_service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=RuntimeError("invalid aggregation"))
    )
    fallback_loader = AsyncMock(return_value={"total_jobs": 2})
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", fallback_loader)

    with pytest.raises(RuntimeError, match="invalid aggregation"):
        await MarketQueryService(statistics_service=statistics_service).get_faceted_stats(object())

    fallback_loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_faceted_stats_reraises_non_retryable_es_http_errors(monkeypatch):
    statistics_service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=_api_error(400))
    )
    fallback_loader = AsyncMock(return_value={"total_jobs": 2})
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", fallback_loader)

    with pytest.raises(ApiError) as caught:
        await MarketQueryService(statistics_service=statistics_service).get_faceted_stats(object())

    assert caught.value.status_code == 400
    fallback_loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_job_search_snapshot_exposes_search_fallback_warning_codes():
    job_search_service = SimpleNamespace(
        search_jobs_with_meta=AsyncMock(
            return_value=(
                [],
                0,
                "postgresql",
                [
                    "Elasticsearch 查询暂时不可用，已降级到 PostgreSQL",
                    "search.es_fallback:ConnectionTimeout",
                ],
            )
        )
    )

    snapshot = await MarketQueryService(job_search_service=job_search_service).search_job_samples(
        object(), keyword="Python"
    )

    assert snapshot.warnings == [
        "Elasticsearch 查询暂时不可用，已降级到 PostgreSQL",
        "search.es_fallback:ConnectionTimeout",
    ]
    assert snapshot.warning_codes == ["search.es_fallback:ConnectionTimeout"]
