from fastapi import APIRouter, Depends, HTTPException, Query
from core.status_code import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from dependencies import get_db, get_current_user
from common.databases.models.favorite import FavoriteJob, FollowCompany
from schemas.favorite import FavoriteJobSchema, FollowCompanySchema

router = APIRouter()

# --- Favorite Jobs ---

@router.get("/jobs", response_model=list[FavoriteJobSchema])
async def get_favorite_jobs(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取收藏的职位列表"""
    stmt = select(FavoriteJob).where(FavoriteJob.user_id == current_user.id)\
        .options(selectinload(FavoriteJob.job))\
        .offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/jobs/{job_id}")
async def favorite_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """收藏职位"""
    # Check if exists
    stmt = select(FavoriteJob).where(FavoriteJob.user_id == current_user.id, FavoriteJob.job_id == job_id)
    result = await db.execute(stmt)
    if result.scalars().first():
        return {"message": "已收藏"}
    
    fav = FavoriteJob(user_id=current_user.id, job_id=job_id)
    db.add(fav)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="收藏失败")
    return {"message": "收藏成功"}

@router.delete("/jobs/{job_id}")
async def unfavorite_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """取消收藏职位"""
    stmt = select(FavoriteJob).where(FavoriteJob.user_id == current_user.id, FavoriteJob.job_id == job_id)
    result = await db.execute(stmt)
    fav = result.scalars().first()
    if not fav:
        raise HTTPException(status_code=StatusCode.NOT_FOUND, detail="未找到收藏记录")
        
    await db.delete(fav)
    await db.commit()
    return {"message": "已取消收藏"}

# --- Follow Companies ---

@router.get("/companies", response_model=list[FollowCompanySchema])
async def get_followed_companies(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取关注的公司列表"""
    stmt = select(FollowCompany).where(FollowCompany.user_id == current_user.id)\
        .offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/companies/{company_id}")
async def follow_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """关注公司"""
    stmt = select(FollowCompany).where(FollowCompany.user_id == current_user.id, FollowCompany.company_id == company_id)
    result = await db.execute(stmt)
    if result.scalars().first():
        return {"message": "已关注"}
    
    follow = FollowCompany(user_id=current_user.id, company_id=company_id)
    db.add(follow)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=StatusCode.BAD_REQUEST, detail="关注失败")
    return {"message": "关注成功"}

@router.delete("/companies/{company_id}")
async def unfollow_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """取消关注公司"""
    stmt = select(FollowCompany).where(FollowCompany.user_id == current_user.id, FollowCompany.company_id == company_id)
    result = await db.execute(stmt)
    follow = result.scalars().first()
    if not follow:
        raise HTTPException(status_code=StatusCode.NOT_FOUND, detail="未找到关注记录")
        
    await db.delete(follow)
    await db.commit()
    return {"message": "已取消关注"}
