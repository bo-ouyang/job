from core.exceptions import AppException
from typing import List
from fastapi import APIRouter, Depends
from core.status_code import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession
from crud import company as crud_company
from schemas.company_schema import CompanyInDB, CompanyList, CompanyCreate, CompanyUpdate
from dependencies import get_db
from dependencies import CommonQueryParams

router = APIRouter()

@router.get("", response_model=CompanyList)
async def read_companies(
    db: AsyncSession = Depends(get_db),
    commons: CommonQueryParams = Depends(),
    industry: str = None,
    location: str = None,
):
    """获取公司列表"""
    companies = await crud_company.search(
        db, 
        keyword=commons.search.q, 
        industry=industry,
        location=location,
        skip=commons.pagination.skip, 
        limit=commons.pagination.page_size
    )
    total = await crud_company.count(db)
    
    return CompanyList(
        items=companies,
        total=total,
        page=commons.pagination.page,
        size=commons.pagination.page_size,
        pages=(total + commons.pagination.page_size - 1) // commons.pagination.page_size
    )

@router.get("/{company_id}", response_model=CompanyInDB)
async def read_company(
    company_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取公司详情"""
    db_company = await crud_company.get(db, id=company_id)
    if not db_company:
        raise AppException(status_code=StatusCode.NOT_FOUND, code=StatusCode.BUSINESS_ERROR, message="Company not found")
    return db_company

@router.post("", response_model=CompanyInDB)
async def create_company(
    company_in: CompanyCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建公司"""
    # 检查公司名称是否已存在
    existing_company = await crud_company.get_by_name(db, name=company_in.name)
    if existing_company:
        raise AppException(status_code=StatusCode.BAD_REQUEST, code=StatusCode.PARAMS_ERROR, message="Company with this name already exists")
    
    return await crud_company.create(db, obj_in=company_in)

@router.put("/{company_id}", response_model=CompanyInDB)
async def update_company(
    company_id: int,
    company_in: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新公司"""
    db_company = await crud_company.get(db, id=company_id)
    if not db_company:
        raise AppException(status_code=StatusCode.NOT_FOUND, code=StatusCode.BUSINESS_ERROR, message="Company not found")
    
    return await crud_company.update(db, db_obj=db_company, obj_in=company_in)
