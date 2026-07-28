from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from common.databases.models.industry import Industry
from common.databases.models.major import MajorIndustryRelation
from crud.job import job as crud_job
from services.analysis_service import analysis_service
from services.comparison_analysis_service import comparison_analysis_service

from .base import AgentTool, ToolContext
from .resolvers import resolve_city, resolve_industry, resolve_industry_codes
from .schemas import (
    CompareCitiesInput,
    CompareIndustriesInput,
    MajorDirectionsInput,
    MarketOverviewInput,
    SkillDemandInput,
    ToolResult,
)


def _bucket_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"name": str(item.get("name") or "未知"), "count": int(item.get("value") or 0)}
        for item in items or []
    ]


class GetMarketOverviewTool(AgentTool[MarketOverviewInput]):
    name = "get_market_overview"
    description = "获取目标职业的岗位量、薪资、技能和行业分布"
    input_model = MarketOverviewInput

    def __init__(self, service=analysis_service):
        self.service = service

    async def execute(self, input_data: MarketOverviewInput, context: ToolContext) -> ToolResult:
        city = await resolve_city(context.db, input_data.cities[0]) if input_data.cities else None
        industry = (
            await resolve_industry(context.db, input_data.industries[0])
            if input_data.industries
            else None
        )
        warnings: List[str] = []
        if len(input_data.cities) > 1:
            warnings.append("市场概览当前只使用第一个城市")
        if len(input_data.industries) > 1:
            warnings.append("市场概览当前只使用第一个行业")

        source = "elasticsearch"
        try:
            stats = await self.service.get_faceted_job_stats(
                keyword=input_data.keyword,
                location=city.code if city else None,
                experience=input_data.experience,
                industry=industry.code if industry and industry.level == 0 else None,
                industry_2=industry.code if industry and industry.level > 0 else None,
            )
            if input_data.education or input_data.salary_min_yuan or input_data.salary_max_yuan:
                warnings.append("当前 ES 市场概览尚未应用学历或薪资过滤")
        except Exception:
            stats = await crud_job.get_statistics_from_db(
                context.db,
                keyword=input_data.keyword,
                location=city.code if city else None,
                experience=input_data.experience,
                education=input_data.education,
                industry=industry.code if industry else None,
                salary_min=input_data.salary_min_yuan,
                salary_max=input_data.salary_max_yuan,
            )
            source = "postgresql"
            warnings.append("Elasticsearch 不可用，已降级到 PostgreSQL")

        total = int(stats.get("total_jobs") or 0)
        filters = input_data.model_dump()
        filters["resolved_city"] = city.__dict__ if city else None
        filters["resolved_industry"] = industry.__dict__ if industry else None
        return ToolResult.success(
            data={
                "job_count": total,
                "salary_distribution": _bucket_list(stats.get("salary") or []),
                "skill_distribution": _bucket_list(stats.get("skills") or []),
                "industry_distribution": _bucket_list(stats.get("industries") or []),
                "education_distribution": [],
                "experience_distribution": [],
                "city_distribution": [],
            },
            sample_size=total,
            filters=filters,
            source=source,
            warnings=warnings,
        )


class GetSkillDemandTool(AgentTool[SkillDemandInput]):
    name = "get_skill_demand"
    description = "统计目标岗位的高频技能和技能覆盖率"
    input_model = SkillDemandInput

    def __init__(self, overview_tool: Optional[GetMarketOverviewTool] = None):
        self.overview_tool = overview_tool or GetMarketOverviewTool()

    async def execute(self, input_data: SkillDemandInput, context: ToolContext) -> ToolResult:
        overview = await self.overview_tool.execute(
            MarketOverviewInput(
                keyword=input_data.keyword,
                cities=input_data.cities,
                industries=input_data.industries,
            ),
            context,
        )
        if not overview.ok:
            return overview
        sample_size = overview.sample_size
        skill_buckets = overview.data.get("skill_distribution", [])[: input_data.limit]
        skills = []
        ratio_warning = False
        for item in skill_buckets:
            count = int(item.get("count") or 0)
            ratio = round(count / sample_size * 100, 2) if sample_size else 0
            if ratio > 100:
                ratio_warning = True
            skills.append({"name": item["name"], "count": count, "ratio": min(ratio, 100.0)})
        warnings = list(overview.warnings)
        if ratio_warning:
            warnings.append("技能同时存在于普通和 AI 标签时可能重复计数，比例已限制为 100%")
        return ToolResult.success(
            data={"skills": skills, "noise_removed": True},
            sample_size=sample_size,
            filters=input_data.model_dump(),
            source=overview.source,
            warnings=warnings,
        )


class GetMajorDirectionsTool(AgentTool[MajorDirectionsInput]):
    name = "get_major_directions"
    description = "根据专业映射和真实岗位样本生成可验证的职业方向"
    input_model = MajorDirectionsInput

    async def execute(self, input_data: MajorDirectionsInput, context: ToolContext) -> ToolResult:
        normalized_major = input_data.major_name.strip()
        relation_result = await context.db.execute(
            select(MajorIndustryRelation).where(
                func.lower(MajorIndustryRelation.major_name) == normalized_major.lower()
            )
        )
        relations = list(relation_result.scalars().all())
        if not relations:
            return ToolResult.success(
                data={"major": normalized_major, "directions": []},
                sample_size=0,
                filters=input_data.model_dump(),
                source="postgresql",
                warnings=["暂无该专业的数据库映射，不能生成已验证方向"],
            )

        codes = set()
        keywords = set()
        for relation in relations:
            for code in relation.industry_codes or []:
                try:
                    codes.add(int(code))
                except (TypeError, ValueError):
                    continue
            keywords.update(
                item.strip()
                for item in str(relation.keywords or "").replace("，", ",").split(",")
                if item.strip()
            )
        expanded_codes = set()
        for code in codes:
            expanded_codes.update(await resolve_industry_codes(context.db, code))
        industry_result = await context.db.execute(
            select(Industry).where(Industry.code.in_(sorted(expanded_codes or codes)))
        )
        industries = list(industry_result.scalars().all())
        directions = [
            {
                "name": industry.name,
                "industry_code": industry.code,
                "source": "database_mapping",
                "verification_status": "verified",
            }
            for industry in sorted(industries, key=lambda item: (item.level, item.rank or 0, item.name))
        ][: input_data.limit]
        return ToolResult.success(
            data={
                "major": normalized_major,
                "directions": directions,
                "keywords": sorted(keywords),
                "job_sample_inference": [],
                "model_inference": [],
            },
            sample_size=len(directions),
            filters=input_data.model_dump(),
            source="postgresql",
            warnings=["当前版本仅返回数据库映射，岗位样本推导将在聚合接口完善后补充"],
        )


def _comparison_side(side) -> Dict[str, Any]:
    value = side.model_dump(mode="json") if hasattr(side, "model_dump") else dict(side)
    overview = value.get("overview") or {}
    return {
        "id": str(value.get("id")),
        "name": value.get("name"),
        "job_count": int(overview.get("sample_size") or 0),
        "salary": {
            "average_yuan": overview.get("salary_avg"),
            "median_yuan": overview.get("salary_median"),
            "p25_yuan": overview.get("salary_p25"),
            "p75_yuan": overview.get("salary_p75"),
        },
        "high_salary_ratio": overview.get("high_salary_ratio"),
        "salary_distribution": value.get("salary_distribution") or [],
        "trend": value.get("trend") or [],
        "education_distribution": value.get("education_distribution") or [],
        "experience_distribution": value.get("experience_distribution") or [],
        "top_skills": value.get("top_skills") or [],
    }


class CompareCitiesTool(AgentTool[CompareCitiesInput]):
    name = "compare_cities"
    description = "比较两个城市在同一职业方向上的岗位、薪资和技能需求"
    input_model = CompareCitiesInput

    def __init__(self, service=comparison_analysis_service):
        self.service = service

    async def execute(self, input_data: CompareCitiesInput, context: ToolContext) -> ToolResult:
        left = await resolve_city(context.db, input_data.cities[0])
        right = await resolve_city(context.db, input_data.cities[1])
        industry = await resolve_industry(context.db, input_data.industry) if input_data.industry else None
        result = await self.service.compare_cities(
            left_city_code=left.code,
            right_city_code=right.code,
            keyword=input_data.keyword,
            industry=industry.code if industry and industry.level == 0 else None,
            industry_2=industry.code if industry and industry.level > 0 else None,
            experience=input_data.experience,
            education=input_data.education,
            days=input_data.days,
        )
        sides = [_comparison_side(result.left), _comparison_side(result.right)]
        return ToolResult.success(
            data={"city_metrics": sides, "summary": result.summary.model_dump(mode="json")},
            sample_size=sum(side["job_count"] for side in sides),
            filters=input_data.model_dump(),
            source="elasticsearch",
            warnings=["城市比较暂不支持 PostgreSQL 降级"],
        )


class CompareIndustriesTool(AgentTool[CompareIndustriesInput]):
    name = "compare_industries"
    description = "比较两个行业在同一职业方向上的岗位、薪资和技能需求"
    input_model = CompareIndustriesInput

    def __init__(self, service=comparison_analysis_service):
        self.service = service

    async def execute(self, input_data: CompareIndustriesInput, context: ToolContext) -> ToolResult:
        left = await resolve_industry(context.db, input_data.industries[0])
        right = await resolve_industry(context.db, input_data.industries[1])
        city = await resolve_city(context.db, input_data.city) if input_data.city else None
        result = await self.service.compare_industries(
            left_industry_code=left.code,
            right_industry_code=right.code,
            keyword=input_data.keyword,
            city_code=city.code if city else None,
            experience=input_data.experience,
            education=input_data.education,
            days=input_data.days,
        )
        sides = [_comparison_side(result.left), _comparison_side(result.right)]
        return ToolResult.success(
            data={"industry_metrics": sides, "summary": result.summary.model_dump(mode="json")},
            sample_size=sum(side["job_count"] for side in sides),
            filters=input_data.model_dump(),
            source="elasticsearch",
            warnings=["行业比较暂不支持 PostgreSQL 降级"],
        )
