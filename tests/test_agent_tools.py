import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from agent.tools.analysis_tools import (
    CompareCitiesTool,
    CompareIndustriesTool,
    GetMajorDirectionsTool,
    GetMarketOverviewTool,
    GetSkillDemandTool,
)
from agent.tools.base import AgentTool, ToolContext
from agent.tools.job_tools import SearchJobsTool
from agent.tools.normalizers import normalize_job
from agent.tools.registry import AgentToolRegistry, agent_tool_registry
from agent.tools.resolvers import ResolvedDimension
from agent.tools.schemas import CompareCitiesInput, SkillDemandInput, ToolResult
from schemas.analysis_schema import CompareAnalysisResponse


class DummyInput(BaseModel):
    value: int


class DummyTool(AgentTool[DummyInput]):
    name = "dummy"
    description = "test"
    input_model = DummyInput

    async def execute(self, input_data, context):
        return ToolResult.success(
            data={"value": input_data.value},
            sample_size=1,
            filters=input_data.model_dump(),
            source="mock",
        )


def test_default_registry_contains_only_approved_tools():
    assert agent_tool_registry.names() == [
        "compare_cities",
        "compare_industries",
        "get_major_directions",
        "get_market_overview",
        "get_skill_demand",
        "search_jobs",
    ]


def test_registry_validates_arguments_and_rejects_unknown_tools():
    registry = AgentToolRegistry()
    registry.register(DummyTool())
    context = ToolContext(db=AsyncMock(), user_id=1)

    valid = asyncio.run(registry.invoke("dummy", {"value": 3}, context))
    invalid = asyncio.run(registry.invoke("dummy", {"value": "not-an-int"}, context))
    unknown = asyncio.run(registry.invoke("missing", {}, context))

    assert valid.ok and valid.data == {"value": 3}
    assert invalid.error_code == "INVALID_TOOL_ARGUMENTS"
    assert unknown.error_code == "UNKNOWN_TOOL"


def test_search_jobs_normalizes_backend_results():
    service = SimpleNamespace(
        search_jobs_with_meta=AsyncMock(
            return_value=(
                [
                    {
                        "id": 9007199254740993,
                        "title": "数据分析师",
                        "salary_min": 10000,
                        "salary_max": 18000,
                        "location": "杭州",
                        "company": {"id": 1, "name": "示例公司"},
                        "industry": {"id": 2, "name": "互联网"},
                        "tags": ["SQL", "Python"],
                    }
                ],
                1,
                "elasticsearch",
                [],
            )
        )
    )
    result = asyncio.run(
        SearchJobsTool(service=service).invoke(
            {"keyword": "数据分析", "limit": 10},
            ToolContext(db=AsyncMock(), user_id=1),
        )
    )

    assert result.ok
    assert result.source == "elasticsearch"
    assert result.data["jobs"][0]["id"] == "9007199254740993"
    assert result.data["common_skills"][0]["name"] in {"SQL", "Python"}


def test_market_overview_falls_back_to_postgresql():
    service = SimpleNamespace(get_faceted_job_stats=AsyncMock(side_effect=RuntimeError("es down")))
    fallback = {
        "salary": [{"name": "10k-15k", "value": 5}],
        "skills": [{"name": "SQL", "value": 4}],
        "industries": [{"name": "互联网", "value": 5}],
        "total_jobs": 5,
    }
    with patch.object(
        __import__("agent.tools.analysis_tools", fromlist=["crud_job"]).crud_job,
        "get_statistics_from_db",
        AsyncMock(return_value=fallback),
    ):
        result = asyncio.run(
            GetMarketOverviewTool(service=service).invoke(
                {"keyword": "数据分析"},
                ToolContext(db=AsyncMock(), user_id=1),
            )
        )

    assert result.ok
    assert result.source == "postgresql"
    assert result.sample_size == 5
    assert result.data["skill_distribution"][0] == {"name": "SQL", "count": 4}


def test_skill_demand_caps_duplicate_tag_ratios():
    overview_tool = SimpleNamespace(
        execute=AsyncMock(
            return_value=ToolResult.success(
                data={"skill_distribution": [{"name": "SQL", "count": 12}]},
                sample_size=10,
                filters={},
                source="elasticsearch",
            )
        )
    )
    result = asyncio.run(
        GetSkillDemandTool(overview_tool=overview_tool).execute(
            SkillDemandInput(keyword="数据分析"),
            ToolContext(db=AsyncMock(), user_id=1),
        )
    )

    assert result.data["skills"][0]["ratio"] == 100
    assert any("重复计数" in warning for warning in result.warnings)


def test_normalize_job_handles_missing_tag_arrays():
    result = normalize_job({"title": "测试职位", "tags": None})
    assert result["skills"] == []
    assert result["company"]["id"] == "0"


def test_compare_input_rejects_duplicate_dimensions():
    with pytest.raises(ValueError):
        CompareCitiesInput(cities=["杭州", "杭州"])


def test_major_directions_returns_explicit_unknown_mapping():
    result_proxy = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result_proxy))
    result = asyncio.run(
        GetMajorDirectionsTool().invoke(
            {"major_name": "不存在的专业"},
            ToolContext(db=db, user_id=1),
        )
    )
    assert result.ok
    assert result.data["directions"] == []
    assert any("暂无" in warning for warning in result.warnings)


def test_compare_cities_normalizes_service_response():
    response = CompareAnalysisResponse.model_validate(
        {
            "dimension": "city",
            "left": {
                "id": 101,
                "name": "杭州",
                "overview": {"sample_size": 10, "salary_median": 15000},
            },
            "right": {
                "id": 102,
                "name": "上海",
                "overview": {"sample_size": 20, "salary_median": 18000},
            },
            "summary": {"winner_dimension": "right", "salary_gap": 3000},
        }
    )
    service = SimpleNamespace(compare_cities=AsyncMock(return_value=response))
    with patch(
        "agent.tools.analysis_tools.resolve_city",
        AsyncMock(
            side_effect=[
                ResolvedDimension(code=101, name="杭州", level=1),
                ResolvedDimension(code=102, name="上海", level=1),
            ]
        ),
    ):
        result = asyncio.run(
            CompareCitiesTool(service=service).invoke(
                {"cities": ["杭州", "上海"]},
                ToolContext(db=AsyncMock(), user_id=1),
            )
        )
    assert result.ok
    assert result.sample_size == 30
    assert result.data["city_metrics"][1]["salary"]["median_yuan"] == 18000


def test_compare_industries_returns_safe_failure():
    service = SimpleNamespace(compare_industries=AsyncMock(side_effect=RuntimeError("es down")))
    with patch(
        "agent.tools.analysis_tools.resolve_industry",
        AsyncMock(
            side_effect=[
                ResolvedDimension(code=1, name="互联网", level=0),
                ResolvedDimension(code=2, name="金融", level=0),
            ]
        ),
    ):
        result = asyncio.run(
            CompareIndustriesTool(service=service).invoke(
                {"industries": ["互联网", "金融"]},
                ToolContext(db=AsyncMock(), user_id=1),
            )
        )
    assert not result.ok
    assert result.error_code == "TOOL_EXECUTION_FAILED"
    assert result.warnings == ["数据服务暂时不可用"]
