from core.logger import sys_logger as logger
import pdfplumber
import json
from jobCollectionWebApi.core.celery_app import celery_app
from services.ai_service import ai_service
from api.v1.endpoints.ws_controller import manager
import asyncio
import os


async def _extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        # Running distinct process for file I/O might be safer but for now direct open
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
    return text

async def _parse_resume_logic(user_id: int, file_path: str):
    """
    1. Extract text from PDF
    2. Call AI to structure data
    3. Notify user via WS
    """
    try:
        text = await _extract_text_from_pdf(file_path)
        if not text:
            await manager.send_personal_message(json.dumps({
                "type": "resume_parse_error",
                "message": "无法读取简历内容，请上传标准的PDF文件"
            }), user_id)
            return

        # Call AI
        parsed_data = await ai_service.parse_resume_text(text)
        logger.debug(f"AI Parsed Data: {parsed_data}")
        # Publish to Redis
        import redis
        from config import settings
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # LOGGING DEBUG INFO
        # works = parsed_data.get('work_experiences', [])
        # edus = parsed_data.get('educations', [])
        # logger.info(f"AI Parsed: {len(works)} works, {len(edus)} educations"y)
        logger.debug(f"DEBUG AI JSON: {json.dumps(parsed_data, ensure_ascii=False)}")
        
        msg = {
            "user_id": user_id,
            "message": {
                "type": "resume_parsed",
                "data": parsed_data
            }
        }
        r.publish("job_messages", json.dumps(msg))
        r.close()
        
    except Exception as e:
        logger.error(f"Resume parsing failed: {e}")
        # Publish error
        import redis
        from config import settings
        try:
            r = redis.from_url(settings.REDIS_URL, decode_responses=True)
            msg = {
                "user_id": user_id,
                "message": {
                    "type": "resume_parse_error",
                    "message": "解析服务暂时不可用"
                }
            }
            r.publish("job_messages", json.dumps(msg))
            r.close()
        except:
            pass

@celery_app.task(bind=True, name="parse_resume_task")
def parse_resume_task(self, user_id: int, file_path: str):
    """Celery task wrapper"""
    loop = asyncio.get_event_loop()
    if loop.is_closed():
             loop = asyncio.new_event_loop()
             asyncio.set_event_loop(loop)
             
    loop.run_until_complete(_parse_resume_logic(user_id, file_path))
