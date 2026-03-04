from core.status_code import StatusCode
from core.exceptions import AppException, AuthFailedException, PermissionDeniedException, ExternalServiceException
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from dependencies import get_db
from crud.city import CityCRUD
from schemas.city_schema import City, CityCreate, CityUpdate
router = APIRouter(tags=["cities"])
city_crud = CityCRUD()

@router.get("/", response_model=List[City])
async def get_cities(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """获取城市列表"""
    return await city_crud.get_cities(db, skip=skip, limit=limit)

@router.get("/level/{level}", response_model=List[City])
async def get_cities_by_level(
    level: int,
    db: AsyncSession = Depends(get_db)
):
    """根据层级获取城市"""
    return await city_crud.get_cities_by_level(db, level)

@router.get("/{city_id}", response_model=City)
async def get_city(
    city_id: int,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取城市"""
    city = await city_crud.get_city(db, city_id)
    if not city:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="城市不存在")
    return city

@router.get("/code/{code}", response_model=City)
async def get_city_by_code(
    code: int,
    db: AsyncSession = Depends(get_db)
):
    """根据编码获取城市"""
    city = await city_crud.get_city_by_code(db, code)
    if not city:
        raise AppException(status_code=404, code=StatusCode.BUSINESS_ERROR, message="城市不存在")
    return city

@router.get("/parent/{parent_id}", response_model=List[City])
async def get_children_cities(
    parent_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取下级城市"""
    return await city_crud.get_children_cities(db, parent_id)
