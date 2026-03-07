import asyncio
from celery import shared_task, current_app
#from celery.utils.log import get_task_logger
from sqlalchemy import select
from typing import List
import json

# Import Database components
from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from core.logger import sys_logger as logger
# Try to import LangChain gracefully, otherwise log warning
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser,PydanticOutputParser
    from pydantic import BaseModel, Field
    import os
    from dotenv import load_dotenv

    # Load environment configuration
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    dotenv_path = os.path.join(project_root, '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    # Output structure
    class JobAnalysisResult(BaseModel):
        """Result of analyzing a job description."""
        skills: List[str] = Field(description="核心技能标签和编程语言 json 数组, e.g. ['Python', 'FastAPI', 'Docker']")
        benefits: List[str] = Field(description="福利待遇 json 数组, e.g. ['年底双薪', '双休']")
        summary: str = Field(description="关于该岗位的1句话简短职责总结")

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False


#logger = get_task_logger(__name__)

def get_env_cleaned(key: str, default: str = None) -> str:
    """Get env var and strip quotes if present."""
    val = os.getenv(key, default)
    if val:
        val = val.strip().strip("'").strip('"')
    return val


def _safe_json_loads(text: str):
    if not isinstance(text, str):
        return None
    content = text.strip()
    if not content:
        return None
    if not ((content.startswith("{") and content.endswith("}")) or (content.startswith("[") and content.endswith("]"))):
        return None
    try:
        return json.loads(content)
    except Exception:
        return None


def _normalize_text(value) -> str:
    """Normalize AI field into plain text for ai_summary."""
    if value is None:
        return ""

    if isinstance(value, str):
        parsed = _safe_json_loads(value)
        if parsed is not None:
            return _normalize_text(parsed)
        return value.strip()

    if isinstance(value, dict):
        # Handle schema-like payloads: {"title": "...", "type": "...", "description": "..."}
        for key in ("summary", "description", "text", "content", "value"):
            if key in value and value.get(key):
                return _normalize_text(value.get(key))
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, (list, tuple, set)):
        parts = [_normalize_text(item) for item in value]
        parts = [p for p in parts if p]
        return "；".join(parts)

    return str(value).strip()


def _normalize_list(value) -> List[str]:
    """Normalize AI field into string list for ai_skills/ai_benefits."""
    if value is None:
        return []

    if isinstance(value, str):
        parsed = _safe_json_loads(value)
        if parsed is not None:
            return _normalize_list(parsed)
        raw = value.strip()
        if not raw:
            return []
        # Fallback split for plain text like "A, B, C"
        split_items = [
            item.strip()
            for item in raw.replace("，", ",").replace("；", ";").replace("、", ",").replace("\n", ",").split(",")
        ]
        return [item for item in split_items if item]

    if isinstance(value, dict):
        # Handle schema-like payloads: {"title":"Skills","type":"array","items":[...]}
        for key in ("items", "data", "list", "skills", "benefits", "value"):
            if key in value:
                return _normalize_list(value.get(key))
        text = _normalize_text(value)
        return [text] if text else []

    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = _normalize_text(item)
                if text:
                    out.append(text)
            else:
                text = _normalize_text(item)
                if text:
                    out.append(text)
        # Deduplicate while preserving order
        seen = set()
        deduped: List[str] = []
        for item in out:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    text = _normalize_text(value)
    return [text] if text else []

async def _process_batch_job_parsing(limit: int = 10):
    """
    异步实际执行解析与库写的协程体 (批量抓取版)
    """
    if not LANGCHAIN_AVAILABLE:
        logger.error("LangChain components not installed. Skipping task.")
        return

    logger.info(f"Start polling for unparsed jobs (limit={limit})...")

    try:
        session_obj = await db_manager.get_session()
        async with session_obj as session:
            # 寻找状态为已爬取 (is_crawl=1) 但未解析 (ai_parsed=0) 的数据
            stmt = select(Job).where(Job.is_crawl == 1, Job.ai_parsed == 0,Job.description != "").limit(limit)
            result = await session.execute(stmt)
            jobs = result.scalars().all()

            if not jobs:
                logger.info("No unparsed jobs found in this polling cycle.")
                return

            logger.info(f"Found {len(jobs)} jobs to parse...")
            
            # Setup AI model once for the batch
            api_key = get_env_cleaned("AI_API_KEY_HUNYUAN")
            base_url = get_env_cleaned("AI_BASE_URL_HUNYUAN")
            model_name = get_env_cleaned("AI_MODEL_HUNYUAN")

            if not api_key:
                logger.error("AI_API_KEY not set. Cannot run parser.")
                return

            llm = ChatOpenAI(
                model=model_name,
                temperature=0,
                openai_api_key=api_key,
                openai_api_base=base_url
            )

            parser = JsonOutputParser(pydantic_object=JobAnalysisResult)
            prompt = ChatPromptTemplate.from_template(
                """
                你是一个资深猎头与技术评测专家。请从以下职位描述中，精准提取并提炼出对应结构的关键信息。
                
                {format_instructions}
                
                职位内容:
                {job_desc}
                """
            )
            chain = prompt | llm | parser

            # ── Controlled concurrency (max 3 parallel LLM calls) ──
            MAX_CONCURRENT = 3
            semaphore = asyncio.Semaphore(MAX_CONCURRENT)

            async def parse_single_job(job):
                """Parse one job with semaphore-controlled concurrency."""
                description = job.description
                if not description:
                    logger.warning(f"Job ID {job.id} has no description to parse. Marking abandoned.")
                    async with (await db_manager.get_session()) as local_session:
                        from sqlalchemy import update
                        await local_session.execute(update(Job).where(Job.id == job.id).values(ai_parsed=2))
                        await local_session.commit()
                    return

                logger.info(f"Invoking LLM for Job ID {job.id}...")

                async with semaphore:
                    try:
                        parsed_result = await chain.ainvoke({
                            "job_desc": description,
                            "format_instructions": parser.get_format_instructions()
                        })

                        # Normalize model output to DB-safe types.
                        summary_value = _normalize_text(parsed_result.get("summary", ""))
                        skills_value = _normalize_list(parsed_result.get("skills", []))
                        benefits_value = _normalize_list(parsed_result.get("benefits", []))

                        from sqlalchemy import update
                        async with (await db_manager.get_session()) as local_session:
                            await local_session.execute(
                                update(Job).where(Job.id == job.id).values(
                                    ai_parsed=2,
                                    ai_skills=skills_value,
                                    ai_benefits=benefits_value,
                                    ai_summary=summary_value
                                )
                            )
                            await local_session.commit()
                        logger.info(f"Successfully updated Job ID {job.id} with AI insight.")
                        try:
                            # Dispatch by task name to avoid package import path issues
                            # (e.g. "No module named 'tasks'" in production workers).
                            current_app.send_task("sync_job_to_es", args=[job.id])
                        except Exception as e:
                            logger.warning(f"Failed to dispatch Celery sync task for new job {job.id}: {e}")
                    except Exception as llm_err:
                        logger.error(f"Error parsing job {job.id}: {llm_err}")
                        # 回滚状态使其参与下一次补漏
                        from sqlalchemy import update
                        async with (await db_manager.get_session()) as local_session:
                            await local_session.execute(update(Job).where(Job.id == job.id).values(ai_parsed=0))
                            await local_session.commit()

            # Pre-lock all jobs to ai_parsed=1 before concurrent processing
            for job in jobs:
                if job.description:
                    job.ai_parsed = 1
                    #from tasks.es_sync import sync_job_to_es
                    # sync_job_to_es.delay(job.id)
            await session.commit()

            # Run all parsing concurrently (bounded by semaphore)
            await asyncio.gather(
                *(parse_single_job(job) for job in jobs),
                return_exceptions=True,
            )
                    
    except Exception as e:
        logger.error(f"Database/Batch error: {e}")
        raise


@shared_task(
    bind=True,
    max_retries=3,
    name="jobCollectionWebApi.tasks.job_parser.process_job_parsing_task",
)
def process_job_parsing_task(self, *args, **kwargs):
    """
    Celery task wrapper for AI batch parsing.
    兼容遗留消息的废弃参数吸收。此任务将由 Celery Beat 定期调用。
    """
    # 建立事件循环用来执行异步 SQLAlchemy 调用
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        # Every cycle we fetch up to 10 jobs to process.
        loop.run_until_complete(_process_batch_job_parsing(limit=10))
        return {"status": "success", "type": "batch_ai_parse"}
    except Exception as exc:
        logger.error(f"process_job_parsing_task failed: {exc}")
        self.retry(exc=exc, countdown=60) # 60秒后重试
