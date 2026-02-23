from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from common.databases.PostgresManager import db_manager
from crud.message import message as crud_message
from schemas.message import MessageCreate, MessageType

from crud.application import application as crud_application
from crud.job import job as crud_job
from schemas.application import ApplicationCreate, ApplicationWithJob
from dependencies import get_current_user
from common.databases.models.user import User
from core.logger import sys_logger as logger

router = APIRouter()

@router.post("/", response_model=ApplicationWithJob)
async def apply_job(
    *,
    db: AsyncSession = Depends(db_manager.get_db),
    application_in: ApplicationCreate,
    current_user: User = Depends(get_current_user)
) -> Any:
    # ... (previous checks)
    job = await crud_job.get(db, id=application_in.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing_application = await crud_application.get_by_user_job(
        db, user_id=current_user.id, job_id=application_in.job_id
    )
    if existing_application:
        raise HTTPException(status_code=400, detail="You have already applied for this job")

    application_data = application_in.dict()
    application_data["user_id"] = current_user.id
    
    application = await crud_application.create(db, obj_in=application_data)
    
    # Trigger System Message
    new_msg = await crud_message.create(db, obj_in=MessageCreate(
        title="投递成功",
        content=f"您已成功投递职位【{job.title}】。请耐心等待HR查看。",
        receiver_id=current_user.id,
        type=MessageType.SYSTEM
    ))
    
    # WebSocket Broadcast
    try:
        from api.v1.endpoints.ws_controller import manager
        # Construct a JSON payload or just text
        msg_payload = {
            "type": "new_message", 
            "data": {
                "title": new_msg.title,
                "content": new_msg.content,
                "id": new_msg.id
            }
        }
        import json
        await manager.send_personal_message(json.dumps(msg_payload), current_user.id)
    except Exception as e:
        # Don't fail the request if WS fails
        logger.error(f"[CRITICAL] WebSocket Broadcast failed for user {current_user.id}: {e}", exc_info=True)
    
    # Manually load job/relations
    application.job = job
    return application

@router.get("/", response_model=List[ApplicationWithJob])
async def read_my_applications(
    db: AsyncSession = Depends(db_manager.get_db),
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get current user's applications
    """
    applications = await crud_application.get_multi_by_user(
        db, user_id=current_user.id, skip=skip, limit=limit
    )
    return applications
