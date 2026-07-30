"""面向 Agent 的真实岗位样本搜索工具。"""

from typing import List, Optional

from services.search_service import search_service

from .base import AgentTool, ToolContext
from .normalizers import build_search_summary, latest_publish_date, normalize_job
from .resolvers import ToolResolutionError, resolve_city, resolve_industry
from .schemas import SearchJobsInput, ToolResult


class SearchJobsTool(AgentTool[SearchJobsInput]):
    """按职业、城市、行业、技能和薪资搜索岗位，并生成紧凑证据摘要。

    当前底层搜索接口一次只接受一个城市和行业，因此多值输入仅使用第一项并返回
    warning；真正的跨城市或跨行业问题应交给专用比较工具。
    """

    name = "search_jobs"
    description = "根据职业关键词、城市、行业、技能和薪资查询真实岗位样本"
    input_model = SearchJobsInput

    def __init__(self, service=search_service):
        """注入岗位搜索服务，默认使用生产 search_service。"""

        self.service = service

    async def execute(self, input_data: SearchJobsInput, context: ToolContext) -> ToolResult:
        """解析维度、执行带来源信息的搜索，并规范化岗位和统计摘要。

        行业名无法映射到数据库时不会直接失败，而是退化为 keyword 查询并明确告警；
        城市必须可靠解析，因为错误城市编码会让市场结论失去意义。
        """

        city = await resolve_city(context.db, input_data.cities[0]) if input_data.cities else None
        warnings: List[str] = []
        industry = None
        keyword = input_data.keyword
        if input_data.industries:
            try:
                industry = await resolve_industry(context.db, input_data.industries[0])
            except ToolResolutionError:
                keyword = keyword or input_data.industries[0]
                warnings.append(
                    f"未识别行业“{input_data.industries[0]}”，已按关键词继续查询"
                )
        if len(input_data.cities) > 1:
            warnings.append("当前搜索版本只使用第一个城市，跨城市查询请使用城市比较工具")
        if len(input_data.industries) > 1:
            warnings.append("当前搜索版本只使用第一个行业，跨行业查询请使用行业比较工具")

        jobs, total, source, backend_warnings = await self.service.search_jobs_with_meta(
            keyword=keyword,
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
