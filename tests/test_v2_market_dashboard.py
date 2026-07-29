from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from schemas.v2.market import MarketDashboardQuery
from services.v2.market_dashboard_service import MarketDashboardService


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
