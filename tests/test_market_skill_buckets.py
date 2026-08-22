import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

comparison_module = importlib.import_module("services.comparison_analysis_service")
from services.comparison_analysis_service import ComparisonAnalysisService
from services.market.skill_buckets import build_skill_aggregations, merge_skill_buckets


def test_comparison_projects_market_skill_buckets_instead_of_merging_them():
    source = (
        ROOT / "jobCollectionWebApi" / "services" / "comparison_analysis_service.py"
    ).read_text(encoding="utf-8")

    assert "from services.market.skill_buckets import merge_skill_buckets" in source
    assert "skill_counter" not in source
    assert "analysis_service._get_skill_noise_rules" not in source


def test_market_skill_aggregation_builder_keeps_the_two_source_contract():
    assert build_skill_aggregations(20) == {
        "top_skills": {"terms": {"field": "skills", "size": 20}},
        "top_ai_skills": {"terms": {"field": "ai_skills", "size": 20}},
    }


def test_merge_skill_buckets_normalizes_filters_and_applies_limit_after_merging():
    result = merge_skill_buckets(
        {
            "top_skills": {
                "buckets": [
                    {"key": " Python  ", "doc_count": 2},
                    {"key": "Other", "doc_count": 9},
                    {"key": "   ", "doc_count": 8},
                    {"key": "SQL", "doc_count": 4},
                ]
            },
            "top_ai_skills": {
                "buckets": [
                    {"key": "Python", "doc_count": 3},
                    {"key": "居家办公", "doc_count": 7},
                ]
            },
        },
        exact_noise={"other"},
        contains_noise=("居家办公",),
        limit=1,
    )

    assert result == [{"name": "Python", "value": 5}]


def test_merge_skill_buckets_keeps_es_input_order_for_equal_counts():
    result = merge_skill_buckets(
        {
            "top_skills": {
                "buckets": [
                    {"key": "Zeta", "doc_count": 3},
                    {"key": "SQL", "doc_count": 3},
                ]
            },
            "top_ai_skills": {"buckets": []},
        },
        exact_noise=set(),
        contains_noise=(),
        limit=2,
    )

    assert result == [
        {"name": "Zeta", "value": 3},
        {"name": "SQL", "value": 3},
    ]


@pytest.mark.asyncio
async def test_comparison_skill_projection_uses_market_noise_rules_and_stable_ties(monkeypatch):
    monkeypatch.setattr(
        comparison_module,
        "get_skill_noise_rules",
        AsyncMock(return_value=({"legacy"}, ("SQL",))),
    )

    result = await ComparisonAnalysisService()._parse_skills(
        {
            "top_skills": {
                "buckets": [
                    {"key": " Python ", "doc_count": 2},
                    {"key": "Legacy", "doc_count": 9},
                    {"key": "sql developer", "doc_count": 8},
                    {"key": "Zeta", "doc_count": 3},
                ]
            },
            "top_ai_skills": {
                "buckets": [
                    {"key": "Python", "doc_count": 3},
                    {"key": "SQL", "doc_count": 3},
                ]
            },
        },
        limit=3,
    )

    assert [(item.name, item.value) for item in result] == [
        ("sql developer", 8),
        ("Python", 5),
        ("Zeta", 3),
    ]
