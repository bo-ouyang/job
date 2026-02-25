from typing import List, Optional, Tuple, Any
from core.logger import sys_logger as logger
from common.databases.PostgresManager import db_manager # Use PostgresManager
from crud.job import job as crud_job # Reuse existing DB search logic
from common.search.conn import get_es
from config import settings


class SearchService:
    """职位搜索服务 (ES + PostgreSQL Fallback Implementation)"""
    
    def __init__(self):
        pass

    async def search_jobs(
        self,
        *,
        keyword: Optional[str] = None,
        location: Optional[int] = None, # updated type based on dict keys
        experience: Optional[str] = None,
        education: Optional[str] = None,
        industry: Optional[str] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[dict], int]:
        """
        基于 ES 的职位全文搜索 (附带 PG 降级保护)
        """
        # --- 优先尝试 Elasticsearch 查询 ---
        try:
            es = await get_es() # Connects to ES implicitly via ESManager
            
            # 构造 DSL 查询
            must_clauses = []
            filter_clauses = []
            
            if keyword:
                must_clauses.append({
                    "multi_match": {
                        "query": keyword,
                        "fields": ["title^3", "description", "requirements", "company_name^2"], # 权重加分
                        "type": "best_fields"
                    }
                })
            else:
                 must_clauses.append({"match_all": {}})
                
            if location:
                filter_clauses.append({"term": {"city_code": location}})
            if experience:
                filter_clauses.append({"prefix": {"experience": experience}})
            if education:
                filter_clauses.append({"prefix": {"education": education}})
                
            # 薪资处理 (单位：元) 因为 PG 侧是实际存的元
            if salary_min is not None:
                filter_clauses.append({"range": {"salary_max": {"gte": salary_min * 1000}}})
            if salary_max is not None:
                filter_clauses.append({"range": {"salary_min": {"lte": salary_max * 1000}}})
                
            query_dsl = {
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "filter": filter_clauses
                    }
                },
                "sort": [
                     {"_score": {"order": "desc"}},
                     {"publish_date": {"order": "desc"}}
                ],
                "from": skip,
                "size": limit
            }
            
            # Request to ES
            response = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            
            total = response["hits"]["total"]["value"]
            hits = response["hits"]["hits"]
            
            job_list = []
            for hit in hits:
                 source = hit["_source"]
                 # 返回 ES document 包含的数据，不需要再查关联表。这是 ES 冗余设计的优势
                 job_list.append({
                     #"id": source.get("id"),
                     "title": source.get("title"),
                     "description": source.get("description"),
                     "requirements": source.get("requirements"),
                     "salary_min": source.get("salary_min"),
                     "salary_max": source.get("salary_max"),
                     "location": str(source.get("city")) if source.get("city") is not None else "",
                     "experience": source.get("experience"),
                     "education": source.get("education"),
                     "publish_date": source.get("publish_date"),
                     "company": {
                         "id": 0, # ES没存公司的主键，暂以0代替，除非修改 mapping
                         "name": source.get("company_name", "")
                     },
                     "industry": {
                         "id": 0, 
                         "name": source.get("industry", "")
                     },
                     "tags": source.get("skills", [])
                 })
                 
            logger.info("Successfully fetched search results from Elasticsearch.")
            return job_list, total

        except Exception as e:
            logger.error(f"Elasticsearch search failed: {e}. Falling back to PostgreSQL DB.")
            
        # --- 如果 ES 宕机或者报错，降级 (Fallback) 到原有的 PostgreSQL `ILIKE` 查询保护主链路 ---
        async with db_manager.async_session() as session:
            jobs, total = await crud_job.search(
                session,
                keyword=keyword,
                location=location,
                experience=experience,
                education=education,
                industry=None, # PostgreSQL search uses ID code not string, needs careful passing
                salary_min=salary_min,
                salary_max=salary_max,
                skip=skip,
                limit=limit
            )
            
            job_list = []
            for job in jobs:
                skills = []
                if job.tags:
                    try:
                        import json
                        skills = job.tags if isinstance(job.tags, (list, dict)) else json.loads(job.tags)
                        if isinstance(skills, str): skills = [skills]
                    except:
                        skills = [str(job.tags)]

                job_dict = {
                    "id": job.id,
                    "title": job.title,
                    "description": job.description,
                    "requirements": job.requirements,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "location": str(job.city_code) if job.city_code is not None else "",
                    "experience": job.experience,
                    "education": job.education,
                    "publish_date": job.publish_date.isoformat() if job.publish_date else None,
                    "company": {
                        "id": job.company.id if job.company else 0,
                        "name": job.company.name if job.company else ""
                    },
                    "industry": {
                        "id": job.industry.id if job.industry else 0,
                        "name": job.industry.name if job.industry else ""
                    },
                    "tags": skills
                }
                job_list.append(job_dict)
                
            return job_list, total

    async def search_jobs_by_ai_intent(self, intent: dict, skip: int = 0, limit: int = 20) -> Tuple[List[dict], int]:
        """
        根据 AI 结构化的解析结果，动态生成并执行 Elasticsearch DSL 检索，包含数据库降级保护。
        """
        try:
            es = await get_es()
            
            must_clauses = []
            should_clauses = []
            must_not_clauses = []
            filter_clauses = []
            
            # 1. 关键词映射 (should 用于加权，必须满足其一)
            keywords = intent.get("keywords") or []
            if keywords:
                for kw in keywords:
                    should_clauses.append({
                        "multi_match": {
                            "query": kw,
                            "fields": ["title^4", "description", "company_name^2"],
                            "type": "best_fields"
                        }
                    })
                must_clauses.append({"bool": {"should": should_clauses, "minimum_should_match": 1}})
            else:
                must_clauses.append({"match_all": {}})
                
            # 2. 地点过滤
            locations = intent.get("locations") or []
            if locations:
                must_clauses.append({
                    "bool": {
                        "should": [{"match": {"city": loc}} for loc in locations],
                        "minimum_should_match": 1
                    }
                })
                
            # 3. 必备技能 (match phrase / wildcard)
            skills = intent.get("skills_must_have") or []
            for sk in skills:
                must_clauses.append({
                    "multi_match": {
                        "query": sk,
                        "fields": ["skills^5", "description", "requirements"]
                    }
                })
                
            # 4. 所需福利 (加权 should，但不强行限制)
            benefits = intent.get("benefits_desired") or []
            for bf in benefits:
                should_clauses.append({"match": {"description": {"query": bf, "boost": 2.0}}})
                
            # 5. 排斥的点 (must_not)
            exclude_keywords = intent.get("exclude_keywords") or []
            for exc in exclude_keywords:
                 must_not_clauses.append({
                     "multi_match": {
                         "query": exc,
                         "fields": ["title", "description", "company_name"]
                     }
                 })
                 
            # 6. 薪资 (filter)
            # 用户输入的如果是如 20000 块，ES如果以元为单位需要乘以 1000（根据您以前代码习惯：salary_min*1000）吗？假设数据已通过脚本同步
            salary_min = intent.get("salary_min")
            if salary_min:
                # 若您的库里实际存的是 k 或是元，这里可以判断。为了健壮性我们做安全校验
                if salary_min < 1000:
                    salary_min = salary_min * 1000
                filter_clauses.append({"range": {"salary_max": {"gte": salary_min}}})
                
            salary_max = intent.get("salary_max")
            if salary_max:
                 if salary_max < 1000:
                     salary_max = salary_max * 1000
                 filter_clauses.append({"range": {"salary_min": {"lte": salary_max}}})

            education = intent.get("education")
            if education and education != "不限":
                filter_clauses.append({"match": {"education": education}})

            query_dsl = {
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "should": should_clauses,
                        "must_not": must_not_clauses,
                        "filter": filter_clauses
                    }
                },
                "sort": [
                     {"_score": {"order": "desc"}},
                     {"publish_date": {"order": "desc"}}
                ],
                "from": skip,
                "size": limit
            }
            
            logger.info(f"AI Search ES DSL assembled: {query_dsl}")
            response = await es.search(index=settings.ES_INDEX_JOB, body=query_dsl)
            total = response["hits"]["total"]["value"]
            
            job_list = []
            for hit in response["hits"]["hits"]:
                 source = hit["_source"]
                 job_list.append({
                     "id": source.get("id"),
                     "title": source.get("title"),
                     "description": source.get("description"),
                     "requirements": source.get("requirements"),
                     "salary_min": source.get("salary_min"),
                     "salary_max": source.get("salary_max"),
                     "location": str(source.get("city")) if source.get("city") else "",
                     "experience": source.get("experience"),
                     "education": source.get("education"),
                     "publish_date": source.get("publish_date"),
                     "company": {"id": 0, "name": source.get("company_name", "")},
                     "industry": {"id": 0, "name": source.get("industry", "")},
                     "tags": source.get("skills", [])
                 })
                 
            return job_list, total
            
        except Exception as e:
            logger.error(f"Elasticsearch AI Search failed: {e}. Falling back to PostgreSQL DB.")
            
        # --- Fallback PostgreSQL ---
        async with db_manager.async_session() as session:
            jobs, total = await crud_job.search_by_ai_intent(
                session,
                intent=intent,
                skip=skip,
                limit=limit
            )
            
            job_list = []
            for job in jobs:
                skills = []
                if job.tags:
                    try:
                        import json
                        skills = job.tags if isinstance(job.tags, (list, dict)) else json.loads(job.tags)
                        if isinstance(skills, str): skills = [skills]
                    except:
                        skills = [str(job.tags)]

                job_list.append({
                    "id": job.id,
                    "title": job.title,
                    "description": job.description,
                    "requirements": job.requirements,
                    "salary_min": job.salary_min,
                    "salary_max": job.salary_max,
                    "location": str(job.city) if job.city else "",
                    "experience": job.experience,
                    "education": job.education,
                    "publish_date": job.publish_date.isoformat() if job.publish_date else None,
                    "company": {"id": job.company.id if job.company else 0, "name": job.company.name if job.company else ""},
                    "industry": {"id": job.industry.id if job.industry else 0, "name": job.industry.name if job.industry else ""},
                    "tags": skills
                })
            return job_list, total

    async def upsert_job(self, job_data: dict):
        """
        同步更新单个职位到 ES
        """
        pass

    async def delete_job(self, job_id: int):
        """
        从 ES 删除单个职位
        """
        pass

search_service = SearchService()
