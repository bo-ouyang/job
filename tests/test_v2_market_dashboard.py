from datetime import datetime, timezone
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from elasticsearch import ConnectionTimeout

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from schemas.v2.market import MarketDashboardQuery
from services.market.query_service import MarketQueryService
from services.v2.market_dashboard_service import MarketDashboardService
from services.market.query_service import MarketQueryService

dashboard_module = importlib.import_module("services.v2.market_dashboard_service")
query_module = importlib.import_module("services.market.query_service")


def test_market_dashboard_depends_on_market_domain_not_agent_tools():
    source = Path(dashboard_module.__file__).read_text(encoding="utf-8")

    assert "agent.tools" not in source
    assert importlib.util.find_spec("services.market.query_service") is not None


@pytest.mark.asyncio
async def test_dashboard_uses_real_stats_and_reports_missing_dimensions():
    async def fake_stats_loader(_query):
        return (
            {
                "total_jobs": 120,
                "salary": [
                    {"name": "10k以下", "value": 30},
                    {"name": "10k-15k", "value": 60},
                    {"name": "15k-25k", "value": 30},
                ],
                "skills": [{"name": "Python", "value": 48}],
                "industries": [{"name": "人工智能", "value": 52}],
            },
            "postgresql",
        )

    service = MarketDashboardService(
        stats_loader=fake_stats_loader,
        now=lambda: datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
    )

    result = await service.get_dashboard(MarketDashboardQuery())

    assert result.kpis[0].value == 120
    assert result.salary_distribution[1].value == 50.0
    assert result.skills[0].name == "Python"
    assert result.data_status.source == "mixed"
    assert result.data_status.degraded is True
    assert "market.monthly_job_trend" in result.data_status.missing_dimensions
    assert "market.normalized_skill_frequency" in result.data_status.missing_dimensions
    assert "market.monthly_job_trend" in result.data_status.synthetic_dimensions
    assert "market.salary_distribution" not in result.data_status.synthetic_dimensions
    assert "market.skill_frequency_raw" not in result.data_status.synthetic_dimensions


@pytest.mark.asyncio
async def test_dashboard_fills_missing_display_dimensions_with_labeled_test_data():
    async def fake_stats_loader(_query):
        return ({"total_jobs": 0, "salary": [], "skills": [], "industries": []}, "postgresql")

    result = await MarketDashboardService(stats_loader=fake_stats_loader).get_dashboard(
        MarketDashboardQuery(city="杭州", industry="人工智能")
    )

    assert result.kpis[0].value == 0
    assert result.kpis[1].value == "¥12,680"
    assert result.trend.series
    assert result.rankings
    assert result.city_matrix
    assert result.city_salaries
    assert result.salary_distribution
    assert result.salary_summary.median is not None
    assert result.talent_structure.education
    assert result.talent_structure.experience
    assert result.data_status.source == "synthetic"
    assert "market.salary_distribution" in result.data_status.synthetic_dimensions
    assert "market.talent_structure" in result.data_status.synthetic_dimensions
    assert "market.salary_percentiles" in result.data_status.missing_dimensions


def test_dashboard_serializes_frontend_camel_case_contract():
    query = MarketDashboardQuery(range="12m", education="本科")
    payload = query.model_dump(by_alias=True)

    assert payload["range"] == "12m"
    assert payload["education"] == "本科"
    assert MarketDashboardService._numeric_code("101210100") == 101210100


@pytest.mark.asyncio
async def test_dashboard_resolves_named_filters_and_applies_date_range(monkeypatch):
    captured = {}

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def resolve_city(_db, value):
        assert value == "杭州"
        return SimpleNamespace(code=101210100)

    async def resolve_industry(_db, value):
        assert value == "互联网/AI"
        return SimpleNamespace(code=100000)

    async def load_stats(_db, **kwargs):
        captured.update(kwargs)
        return {"total_jobs": 7, "salary": [], "skills": [], "industries": []}

    monkeypatch.setattr(query_module.settings, "ES_ENABLED", False)
    monkeypatch.setattr(dashboard_module.db_manager, "async_session", lambda: SessionContext())
    monkeypatch.setattr(query_module, "resolve_city", resolve_city)
    monkeypatch.setattr(query_module, "resolve_industry", resolve_industry)
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", load_stats)

    service = MarketDashboardService(
        now=lambda: datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )
    raw, source = await service._load_stats(
        MarketDashboardQuery(range="30d", city="杭州", industry="互联网/AI")
    )

    assert raw["total_jobs"] == 7
    assert source == "postgresql"
    assert captured["location"] == 101210100
    assert captured["industry"] == 100000
    assert captured["published_after"] == datetime(2026, 7, 6, 12, 0)


@pytest.mark.asyncio
async def test_dashboard_attempts_elasticsearch_before_postgresql_fallback(monkeypatch):
    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    statistics_service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=ConnectionTimeout("es down"))
    )
    fallback_loader = AsyncMock(
        return_value={"total_jobs": 2, "salary": [], "skills": [], "industries": []}
    )
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(dashboard_module.db_manager, "async_session", lambda: SessionContext())
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", fallback_loader)

    raw, source = await MarketDashboardService(
        query_service=MarketQueryService(statistics_service=statistics_service)
    )._load_stats(MarketDashboardQuery(education="本科"))

    assert raw["total_jobs"] == 2
    assert source == "postgresql"
    statistics_service.get_faceted_job_stats.assert_awaited_once()
    assert fallback_loader.await_args.kwargs["education"] == "本科"


@pytest.mark.asyncio
async def test_dashboard_falls_back_to_postgresql_when_es_statistics_fail(monkeypatch):
    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    fallback = {"total_jobs": 4, "salary": [], "skills": [], "industries": []}
    load_stats = AsyncMock(return_value=fallback)
    failed_statistics = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=ConnectionTimeout("es unavailable"))
    )
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    monkeypatch.setattr(dashboard_module.db_manager, "async_session", lambda: SessionContext())
    monkeypatch.setattr(query_module.crud_job, "get_statistics_from_db", load_stats)

    service = MarketDashboardService(
        query_service=MarketQueryService(statistics_service=failed_statistics)
    )
    raw, source = await service._load_stats(MarketDashboardQuery())

    assert raw == fallback
    assert source == "postgresql"
    load_stats.assert_awaited_once()
