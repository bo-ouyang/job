"""V2 message-center API with paginated, structured notification fields."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.PostgresManager import db_manager
from crud.message import message as crud_message
from dependencies import get_current_user
from schemas.v2.message import MessagePageResponse


router = APIRouter()


@router.get("/", response_model=MessagePageResponse)
async def list_messages(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool | None = Query(default=None, alias="unreadOnly"),
    legacy_unread_only: bool | None = Query(default=None, alias="unread_only"),
    category: str | None = Query(default=None, max_length=30),
    status: str | None = Query(default=None, max_length=30),
    db: AsyncSession = Depends(db_manager.get_db),
    current_user=Depends(get_current_user),
):
    messages, total = await crud_message.get_my_messages_page(
        db,
        receiver_id=current_user.id,
        skip=skip,
        limit=limit,
        unread_only=(unread_only if unread_only is not None else bool(legacy_unread_only)),
        category=category,
        status=status,
    )
    return MessagePageResponse(items=messages, total=total, skip=skip, limit=limit)
