from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from common.databases.PostgresManager import db_manager
from crud.message import message as crud_message
from schemas.message import Message
from dependencies import get_current_user
from common.databases.models.user import User

router = APIRouter()

@router.get("/", response_model=List[Message])
async def read_messages(
    db: AsyncSession = Depends(db_manager.get_db),
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get current user's messages
    """
    messages = await crud_message.get_my_messages(
        db, receiver_id=current_user.id, skip=skip, limit=limit
    )
    return messages

@router.get("/unread-count", response_model=int)
async def get_unread_count(
    db: AsyncSession = Depends(db_manager.get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get unread message count
    """
    return await crud_message.get_unread_count(db, receiver_id=current_user.id)

@router.put("/{msg_id}/read", response_model=Message)
async def mark_message_read(
    msg_id: int,
    db: AsyncSession = Depends(db_manager.get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Mark message as read
    """
    msg = await crud_message.get(db, id=msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.receiver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your message")
    
    if not msg.is_read:
        msg = await crud_message.update(db, db_obj=msg, obj_in={"is_read": True})
    return msg

@router.post("/mark-all-read")
async def mark_all_read(
    db: AsyncSession = Depends(db_manager.get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Mark all messages as read
    """
    await crud_message.mark_all_read(db, receiver_id=current_user.id)
    return {"status": "success"}
