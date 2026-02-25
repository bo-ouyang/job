import asyncio
from celery import shared_task
#from celery.utils.log import get_task_logger
from sqlalchemy import select
from typing import List

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

            # 串行处理 (防止并发过高炸 API)
            for job in jobs:
                description = job.description
                if not description:
                    logger.warning(f"Job ID {job.id} has no description to parse. Marking abandoned.")
                    job.ai_parsed = 2 # Prevent looping
                    continue
                
                logger.info(f"Invoking LLM for Job ID {job.id}...")
                
                # State: Pre-parsing Lock
                job.ai_parsed = 1
                await session.commit()
                
                try:
                    parsed_result = await chain.ainvoke({
                        "job_desc": description,
                        "format_instructions": parser.get_format_instructions()
                    })
                    
                    # JsonOutputParser returns a dict
                    job.ai_parsed = 2
                    job.ai_skills = parsed_result.get('skills', [])
                    job.ai_benefits = parsed_result.get('benefits', [])
                    job.ai_summary = parsed_result.get('summary', '')
                    await session.commit()
                    logger.info(f"Successfully updated Job ID {job.id} with AI insight.")
                    try:
                        from tasks.es_sync import sync_job_to_es
                        #sync_job_to_es.delay()
                        sync_job_to_es.delay(job.id)
                    except Exception as e:
                        logger.warning(f"Failed to dispatch Celery sync task for new job {job.id}: {e}")
                except Exception as llm_err:
                    logger.error(f"Error parsing job {job.id}: {llm_err}")
                    # 回滚状态使其参与下一次补漏
                    job.ai_parsed = 0
                    await session.commit()
                    
    except Exception as e:
        logger.error(f"Database/Batch error: {e}")
        raise


@shared_task(bind=True, max_retries=3)
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
