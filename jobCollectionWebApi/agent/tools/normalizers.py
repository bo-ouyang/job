"""把搜索服务返回的岗位记录转换为稳定、紧凑的 Agent 证据。"""

from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def normalize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """规范单条岗位记录的字段、类型和技能标签。

    搜索后端可能返回不同形态的数据，本函数屏蔽这些差异，并只保留回答所需字段。
    """

    tags = job.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    company = job.get("company") or {}
    industry = job.get("industry") or {}
    return {
        "id": str(job.get("id")) if job.get("id") is not None else None,
        "title": str(job.get("title") or ""),
        "description": str(job.get("description") or ""),
        "requirements": str(job.get("requirements") or ""),
        "salary_min_yuan": job.get("salary_min"),
        "salary_max_yuan": job.get("salary_max"),
        "city": str(job.get("location") or ""),
        "experience": job.get("experience"),
        "education": job.get("education"),
        "publish_date": job.get("publish_date"),
        "company": {"id": str(company.get("id") or "0"), "name": company.get("name") or ""},
        "industry": {"id": str(industry.get("id") or "0"), "name": industry.get("name") or ""},
        "skills": sorted({str(tag).strip() for tag in tags if str(tag).strip()}),
    }


def latest_publish_date(jobs: Iterable[Dict[str, Any]]) -> Optional[datetime]:
    """返回岗位样本中的最新发布日期，无法解析的日期会被忽略。"""

    values: List[datetime] = []
    for job in jobs:
        raw = job.get("publish_date")
        if isinstance(raw, datetime):
            values.append(raw)
        elif raw:
            try:
                values.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
            except ValueError:
                continue
    return max(values) if values else None


def build_search_summary(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从岗位样本汇总热门职位、城市、技能和基础薪资范围。"""

    titles = Counter(job["title"] for job in jobs if job.get("title"))
    cities = Counter(job["city"] for job in jobs if job.get("city"))
    skills = Counter(skill for job in jobs for skill in job.get("skills", []))
    salary_values = [
        value
        for job in jobs
        for value in (job.get("salary_min_yuan"), job.get("salary_max_yuan"))
        if isinstance(value, (int, float)) and value > 0
    ]
    return {
        "top_titles": [{"name": name, "count": count} for name, count in titles.most_common(10)],
        "top_cities": [{"name": name, "count": count} for name, count in cities.most_common(10)],
        "common_skills": [{"name": name, "count": count} for name, count in skills.most_common(15)],
        "salary_summary": {
            "min_yuan": min(salary_values) if salary_values else None,
            "max_yuan": max(salary_values) if salary_values else None,
            "average_yuan": round(sum(salary_values) / len(salary_values), 2) if salary_values else None,
        },
    }
