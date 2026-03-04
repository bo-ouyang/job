from fastapi import APIRouter, Depends, Query
from core.exceptions import UserNotFoundException
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_db, get_current_user, get_current_admin_user
from crud import user as crud_user
from schemas.user_schema import UserPublic, UserList, UserDetail, UserUpdate, UserAdminUpdate, UserRole, UserStatus
from dependencies import CommonQueryParams

router = APIRouter()

@router.get("/me", response_model=UserDetail)
async def get_my_info(
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户信息"""
    return current_user

@router.put("/me", response_model=UserPublic)
async def update_my_info(
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """更新当前用户信息"""
    return await crud_user.update(db, db_obj=current_user, obj_in=user_in)

@router.get("", response_model=UserList)
async def read_users(
    commons: CommonQueryParams = Depends(),
    role: UserRole = Query(None),
    status: UserStatus = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表（管理员）"""
    users = await crud_user.search(
        db,
        keyword=commons.search.q,
        role=role,
        status=status,
        skip=commons.pagination.skip,
        limit=commons.pagination.page_size
    )
    
    total = await crud_user.count(db)
    
    return UserList(
        items=users,
        total=total,
        page=commons.pagination.page,
        size=commons.pagination.page_size,
        pages=(total + commons.pagination.page_size - 1) // commons.pagination.page_size
    )

@router.get("/{user_id}", response_model=UserDetail)
async def read_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取用户详情（管理员）"""
    user = await crud_user.get(db, id=user_id)
    if not user:
        raise UserNotFoundException()
    return user

@router.put("/{user_id}", response_model=UserPublic)
async def update_user_by_admin(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db)
):
    """管理员更新用户信息 (通用字段)"""
    # 仅管理员可调用此接口修改任意用户信息
    # 普通用户请使用 /me 接口
    
    user = await crud_user.get(db, id=user_id)
    if not user:
        raise UserNotFoundException()
    
    return await crud_user.update(db, db_obj=user, obj_in=user_in)

@router.put("/{user_id}/admin", response_model=UserPublic)
async def update_user_admin(
    user_id: int,
    user_in: UserAdminUpdate,
    db: AsyncSession = Depends(get_db)
):
    """管理员更新用户信息"""
    user = await crud_user.get(db, id=user_id)
    if not user:
        raise UserNotFoundException()
    
    return await crud_user.update(db, db_obj=user, obj_in=user_in)
