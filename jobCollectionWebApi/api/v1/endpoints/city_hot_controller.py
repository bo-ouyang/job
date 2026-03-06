from core.status_code import StatusCode
from core.exceptions import AppException
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from dependencies import get_db
from crud.city_hot import CityHotCRUD
from schemas.city_hot_schema import CityHot
router = APIRouter(tags=["city_hots"])
city_hot_crud = CityHotCRUD()

@router.get("/", response_model=List[CityHot])
async def get_cities(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """获取城市列表"""
    return await city_hot_crud.get_city_hots(db, skip=skip, limit=limit)

@router.get("/level/{level}", response_model=List[CityHot])
async def get_cities_by_level(
    level: int,
    db: AsyncSession = Depends(get_db)
):
    """根据层级获取城市"""
    return await city_hot_crud.get_city_hots_by_level(db, level)

@router.get("/{city_id}", response_model=CityHot)
async def get_city(
    city_id: int,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取城市"""
    city = await city_hot_crud.get_city_hot(db, city_id)
    if not city:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="城市不存在")
    return city

@router.get("/code/{code}", response_model=CityHot)
async def get_city_by_code(
    code: int,
    db: AsyncSession = Depends(get_db)
):
    """根据编码获取城市"""
    city = await city_hot_crud.get_city_hot_by_code(db, code)
    if not city:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="城市不存在")
    return city

@router.get("/parent/{parent_id}", response_model=List[CityHot])
async def get_children_cities(
    parent_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取下级城市"""
    return await city_hot_crud.get_children_city_hots(db, parent_id)
