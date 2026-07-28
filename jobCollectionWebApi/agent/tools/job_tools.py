from typing import List, Optional

from services.search_service import search_service

from .base import AgentTool, ToolContext
from .normalizers import build_search_summary, latest_publish_date, normalize_job
from .resolvers import resolve_city, resolve_industry
from .schemas import SearchJobsInput, ToolResult


class SearchJobsTool(AgentTool[SearchJobsInput]):
    name = "search_jobs"
    description = "根据职业关键词、城市、行业、技能和薪资查询真实岗位样本"
    input_model = SearchJobsInput

    def __init__(self, service=search_service):
        self.service = service

    async def execute(self, input_data: SearchJobsInput, context: ToolContext) -> ToolResult:
        city = await resolve_city(context.db, input_data.cities[0]) if input_data.cities else None
        industry = (
            await resolve_industry(context.db, input_data.industries[0])
            if input_data.industries
            else None
        )
        warnings: List[str] = []
        if len(input_data.cities) > 1:
            warnings.append("当前搜索版本只使用第一个城市，跨城市查询请使用城市比较工具")
        if len(input_data.industries) > 1:
            warnings.append("当前搜索版本只使用第一个行业，跨行业查询请使用行业比较工具")

        jobs, total, source, backend_warnings = await self.service.search_jobs_with_meta(
            keyword=input_data.keyword,
            location=city.code if city else None,
            experience=input_data.experience,
            education=input_data.education,
            industry=industry.code if industry else None,
            skills=input_data.skills,
            salary_min=(input_data.salary_min_yuan / 1000 if input_data.salary_min_yuan is not None else None),
            salary_max=(input_data.salary_max_yuan / 1000 if input_data.salary_max_yuan is not None else None),
            limit=input_data.limit,
        )
        normalized_jobs = [normalize_job(job) for job in jobs]
        filters = input_data.model_dump()
        filters["resolved_city"] = city.__dict__ if city else None
        filters["resolved_industry"] = industry.__dict__ if industry else None
        return ToolResult.success(
            data={
                "total": total,
                "jobs": normalized_jobs,
                **build_search_summary(normalized_jobs),
            },
            sample_size=total,
            filters=filters,
            data_as_of=latest_publish_date(normalized_jobs),
            source=source,
            warnings=warnings + backend_warnings,
        )
