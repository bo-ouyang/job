import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from services import analysis_service as analysis_module
from services.analysis_service import AnalysisService


EMPTY_MARKET_STATS = {"salary": [], "skills": [], "industries": [], "total_jobs": 0}


def test_market_aggregation_builder_keeps_standard_bucket_contract():
    dsl = AnalysisService._build_market_aggregation_dsl({"filter": [{"term": {"city_code": 1}}]})

    assert dsl["query"] == {"bool": {"filter": [{"term": {"city_code": 1}}]}}
    assert dsl["size"] == 0
    assert dsl["track_total_hits"] is True
    assert dsl["aggs"]["salary_ranges"] == {
        "range": {
            "field": "salary_min",
            "ranges": [
                {"to": 10000.0, "key": "10k以下"},
                {"from": 10000.0, "to": 15000.0, "key": "10k-15k"},
                {"from": 15000.0, "to": 25000.0, "key": "15k-25k"},
                {"from": 25000.0, "to": 35000.0, "key": "25k-35k"},
                {"from": 35000.0, "key": "35k以上"},
            ],
        }
    }
    assert dsl["aggs"]["top_industries"] == {"terms": {"field": "industry_code", "size": 10}}
    assert dsl["aggs"]["top_skills"] == {"terms": {"field": "skills", "size": 15}}
    assert dsl["aggs"]["top_ai_skills"] == {"terms": {"field": "ai_skills", "size": 15}}


@pytest.mark.asyncio
async def test_career_es_failure_returns_normalized_empty_market_stats(monkeypatch):
    service = AnalysisService()
    es = type("FailingEs", (), {"search": AsyncMock(side_effect=RuntimeError("es down"))})()
    monkeypatch.setattr(analysis_module, "get_es", AsyncMock(return_value=es))

    result = await service._get_es_career_analysis([], None, None, None)

    assert result == EMPTY_MARKET_STATS


@pytest.mark.asyncio
async def test_home_es_failure_returns_normalized_empty_market_stats(monkeypatch):
    service = AnalysisService()
    es = type("FailingEs", (), {"search": AsyncMock(side_effect=RuntimeError("es down"))})()
    monkeypatch.setattr(analysis_module, "get_es", AsyncMock(return_value=es))

    result = await service.get_home_stats.__wrapped__(service)

    assert result == EMPTY_MARKET_STATS


@pytest.mark.asyncio
async def test_faceted_es_failure_is_reraised_for_market_postgresql_fallback(monkeypatch):
    service = AnalysisService()
    es = type("FailingEs", (), {"search": AsyncMock(side_effect=RuntimeError("es down"))})()
    monkeypatch.setattr(analysis_module, "get_es", AsyncMock(return_value=es))

    with pytest.raises(RuntimeError, match="es down"):
        await service.get_faceted_job_stats(keyword="Python")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "load_stats",
    [
        lambda service: service._get_es_career_analysis([], None, None, None),
        lambda service: service.get_home_stats.__wrapped__(service),
        lambda service: service.get_faceted_job_stats(),
    ],
    ids=["career", "home", "faceted"],
)
async def test_standard_market_stats_accept_missing_aggregations(monkeypatch, load_stats):
    service = AnalysisService()
    es = type(
        "EmptyAggregationEs",
        (),
        {"search": AsyncMock(return_value={"hits": {"total": {"value": 7}}})},
    )()
    monkeypatch.setattr(analysis_module, "get_es", AsyncMock(return_value=es))
    monkeypatch.setattr(analysis_module, "get_skill_noise_rules", AsyncMock(return_value=(set(), ())))

    result = await load_stats(service)

    assert result == {**EMPTY_MARKET_STATS, "total_jobs": 7}


@pytest.mark.asyncio
async def test_market_aggregation_projector_normalizes_and_filters_skill_buckets(monkeypatch):
    service = AnalysisService()
    monkeypatch.setattr(
        analysis_module,
        "get_skill_noise_rules",
        AsyncMock(return_value=({"other"}, ("居家办公",))),
    )
    aggs = {
        "salary_ranges": {"buckets": [{"key": "10k以下", "doc_count": 3}]},
        "top_industries": {"buckets": []},
        "top_skills": {
            "buckets": [
                {"key": " Python  ", "doc_count": 2},
                {"key": "Other", "doc_count": 9},
            ]
        },
        "top_ai_skills": {
            "buckets": [
                {"key": "Python", "doc_count": 4},
                {"key": "居家办公", "doc_count": 8},
            ]
        },
    }

    result = await service._project_market_aggregations(aggs)

    assert result == {
        "salary": [{"name": "10k以下", "value": 3}],
        "skills": [{"name": "Python", "value": 6}],
        "industries": [],
    }


@pytest.mark.asyncio
async def test_skill_bucket_projector_applies_shared_limit_after_merging(monkeypatch):
    service = AnalysisService()
    monkeypatch.setattr(
        analysis_module,
        "get_skill_noise_rules",
        AsyncMock(return_value=(set(), ())),
    )

    result = await service._project_skill_buckets(
        {
            "top_skills": {
                "buckets": [
                    {"key": "Python", "doc_count": 2},
                    {"key": "SQL", "doc_count": 4},
                ]
            },
            "top_ai_skills": {"buckets": [{"key": "Python", "doc_count": 3}]},
        },
        limit=1,
    )

    assert result == [{"name": "Python", "value": 5}]
