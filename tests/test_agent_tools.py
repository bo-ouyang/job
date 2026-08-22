import asyncio
import inspect
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from elasticsearch import ConnectionTimeout
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
from agent.tools.resolvers import ResolvedDimension, ToolResolutionError, resolve_city
from agent.tools.schemas import CompareCitiesInput, SkillDemandInput, ToolResult
from schemas.analysis_schema import CompareAnalysisResponse
from services.market.query_service import MarketQueryService, MarketStatisticsSnapshot


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


class ResolutionFailureTool(DummyTool):
    async def execute(self, input_data, context):
        raise ToolResolutionError("unknown or ambiguous city: 上海")


def test_default_registry_contains_only_approved_tools():
    assert agent_tool_registry.names() == [
        "compare_cities",
        "compare_industries",
        "get_major_directions",
        "get_market_overview",
        "get_skill_demand",
        "search_jobs",
    ]


def test_agent_market_tools_depend_on_market_query_service_not_low_level_services():
    analysis_source = Path(
        __import__("agent.tools.analysis_tools", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")
    job_source = Path(
        __import__("agent.tools.job_tools", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")

    assert "services.market.query_service" in analysis_source
    assert "services.analysis_service" not in analysis_source
    assert "crud.job" not in analysis_source
    assert "services.market.query_service" in job_source
    assert "services.search_service" not in job_source
    assert ".resolvers" not in job_source
    assert "query_service" in inspect.signature(GetMarketOverviewTool).parameters
    assert "query_service" in inspect.signature(SearchJobsTool).parameters


def test_agent_tool_base_only_depends_on_lightweight_market_error():
    source = Path(
        __import__("agent.tools.base", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")

    assert "services.market.errors import MarketResolutionError" in source
    assert "services.market.query_service" not in source


def test_market_error_import_does_not_load_query_service():
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'jobCollectionWebApi')!r}); "
        "import services.market.errors; "
        "assert 'services.market.query_service' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_agent_tool_base_import_does_not_load_market_query_dependencies():
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'jobCollectionWebApi')!r}); "
        "import agent.tools.base; "
        "assert 'services.market.query_service' not in sys.modules; "
        "assert 'services.analysis_service' not in sys.modules; "
        "assert 'services.search_service' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_agent_tools_package_lazily_exposes_working_registry():
    import agent.tools as tools

    assert tools.agent_tool_registry.names() == agent_tool_registry.names()


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


def test_city_resolver_prefers_the_city_level_record_for_a_municipality():
    result_proxy = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(code=101020000, name="上海", level=0),
                SimpleNamespace(code=101020100, name="上海", level=1),
            ]
        )
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=result_proxy))

    resolved = asyncio.run(resolve_city(db, "上海"))

    assert resolved == ResolvedDimension(code=101020100, name="上海", level=1)


def test_tool_returns_the_dimension_resolution_error_instead_of_hiding_it():
    result = asyncio.run(
        ResolutionFailureTool().invoke(
            {"value": 1},
            ToolContext(db=AsyncMock(), user_id=1),
        )
    )

    assert result.error_code == "DIMENSION_RESOLUTION_FAILED"
    assert result.warnings == ["城市或行业解析失败：unknown or ambiguous city: 上海"]


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
        SearchJobsTool(query_service=MarketQueryService(job_search_service=service)).invoke(
            {"keyword": "数据分析", "limit": 10},
            ToolContext(db=AsyncMock(), user_id=1),
        )
    )

    assert result.ok
    assert result.source == "elasticsearch"
    assert result.data["jobs"][0]["id"] == "9007199254740993"
    assert result.data["common_skills"][0]["name"] in {"SQL", "Python"}


def test_search_jobs_treats_an_unknown_industry_label_as_a_keyword():
    empty_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=empty_result))
    service = SimpleNamespace(
        search_jobs_with_meta=AsyncMock(return_value=([], 0, "postgresql", []))
    )

    result = asyncio.run(
        SearchJobsTool(query_service=MarketQueryService(job_search_service=service)).invoke(
            {"keyword": "人工智能", "industries": ["人工智能"], "limit": 10},
            ToolContext(db=db, user_id=1),
        )
    )

    assert result.ok
    service.search_jobs_with_meta.assert_awaited_once()
    assert service.search_jobs_with_meta.await_args.kwargs["keyword"] == "人工智能"
    assert service.search_jobs_with_meta.await_args.kwargs["industry"] is None
    assert any("关键词" in warning for warning in result.warnings)


def test_market_overview_falls_back_to_postgresql(monkeypatch):
    query_module = __import__("services.market.query_service", fromlist=["settings"])
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(side_effect=ConnectionTimeout("es down"))
    )
    fallback = {
        "salary": [{"name": "10k-15k", "value": 5}],
        "skills": [{"name": "SQL", "value": 4}],
        "industries": [{"name": "互联网", "value": 5}],
        "total_jobs": 5,
    }
    fallback_loader = AsyncMock(return_value=fallback)
    with patch.object(
        __import__("services.market.query_service", fromlist=["crud_job"]).crud_job,
        "get_statistics_from_db",
        fallback_loader,
    ):
        result = asyncio.run(
            GetMarketOverviewTool(
                query_service=MarketQueryService(statistics_service=service)
            ).invoke(
                {"keyword": "数据分析", "education": "本科"},
                ToolContext(db=AsyncMock(), user_id=1),
            )
        )

    assert result.ok
    assert result.source == "postgresql"
    assert result.sample_size == 5
    assert result.data["skill_distribution"][0] == {"name": "SQL", "count": 4}
    assert any("已降级到 PostgreSQL" in warning for warning in result.warnings)
    assert not any(warning.startswith("market.stats.es_fallback:") for warning in result.warnings)
    service.get_faceted_job_stats.assert_awaited_once()
    assert fallback_loader.await_args.kwargs["education"] == "本科"


def test_market_overview_treats_an_unknown_industry_label_as_a_keyword(monkeypatch):
    query_module = __import__("services.market.query_service", fromlist=["settings"])
    monkeypatch.setattr(query_module.settings, "ES_ENABLED", True)
    empty_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=empty_result))
    service = SimpleNamespace(
        get_faceted_job_stats=AsyncMock(
            return_value={
                "salary": [],
                "skills": [],
                "industries": [],
                "total_jobs": 3,
            }
        )
    )

    result = asyncio.run(
        GetMarketOverviewTool(
            query_service=MarketQueryService(statistics_service=service)
        ).invoke(
            {
                "keyword": "人工智能",
                "industries": ["人工智能"],
                "education": "本科",
            },
            ToolContext(db=db, user_id=1),
        )
    )

    assert result.ok
    assert result.sample_size == 3
    assert service.get_faceted_job_stats.await_args.kwargs["keyword"] == "人工智能"
    assert service.get_faceted_job_stats.await_args.kwargs["industry"] is None
    assert service.get_faceted_job_stats.await_args.kwargs["education"] is None
    assert any("关键词" in warning for warning in result.warnings)
    assert any("学历" in warning for warning in result.warnings)


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
        "services.market.query_service.resolve_city",
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
        "services.market.query_service.resolve_industry",
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
