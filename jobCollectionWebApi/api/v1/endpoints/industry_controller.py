# jobCollectionWebApi/routers/industry.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from dependencies import get_db
from crud.industry import IndustryCRUD
from schemas.industry import Industry, IndustryCreate, IndustryUpdate, IndustryTree, IndustryResponse

router = APIRouter(prefix="/industries", tags=["industries"])
industry_crud = IndustryCRUD()

@router.get("/", response_model=List[Industry])
async def get_industries(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """获取行业列表"""
    return await industry_crud.get_industries(db, skip=skip, limit=limit)

@router.get("/{industry_id}", response_model=Industry)
async def get_industry(
    industry_id: int,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取行业"""
    industry = await industry_crud.get_industry(db, industry_id)
    if not industry:
        raise HTTPException(status_code=404, detail="行业不存在")
    return industry

@router.get("/code/{code}", response_model=Industry)
async def get_industry_by_code(
    code: int,
    db: AsyncSession = Depends(get_db)
):
    """根据编码获取行业"""
    industry = await industry_crud.get_industry_by_code(db, code)
    if not industry:
        raise HTTPException(status_code=404, detail="行业不存在")
    return industry

@router.get("/level/{level}", response_model=List[Industry])
async def get_industries_by_level(
    level: int,
    db: AsyncSession = Depends(get_db)
):
    """根据层级获取行业"""
    return await industry_crud.get_industries_by_level(db, level)

@router.get("/parent/{parent_id}", response_model=List[Industry])
async def get_children_industries(
    parent_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取子行业"""
    return await industry_crud.get_children_industries(db, parent_id)

@router.get("/tree/", response_model=List[IndustryTree])
async def get_industry_tree(
    parent_id: Optional[int] = Query(None, description="父级ID，为空则获取所有一级行业"),
    db: AsyncSession = Depends(get_db)
):
    """获取行业树形结构"""
    return await industry_crud.get_industry_tree(db, parent_id)

@router.post("/", response_model=Industry)
async def create_industry(
    industry: IndustryCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建行业"""
    industry_data = industry.dict()
    return await industry_crud.upsert_industry(db, industry_data)

@router.put("/{industry_id}", response_model=Industry)
async def update_industry(
    industry_id: int,
    industry: IndustryUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新行业"""
    # 先检查行业是否存在
    existing = await industry_crud.get_industry(db, industry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="行业不存在")
    
    industry_data = industry.dict(exclude_unset=True)
    industry_data["code"] = existing.code  # 保持code不变
    return await industry_crud.upsert_industry(db, industry_data)

@router.delete("/{industry_id}", response_model=IndustryResponse)
async def delete_industry(
    industry_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除行业"""
    industry = await industry_crud.delete_industry(db, industry_id)
    if not industry:
        raise HTTPException(status_code=404, detail="行业不存在")
    
    return IndustryResponse(
        success=True,
        message="行业删除成功",
        data={"id": industry_id}
    )

@router.post("/bulk/", response_model=IndustryResponse)
async def bulk_insert_industries(
    industries: List[IndustryCreate],
    batch_size: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """批量插入行业数据"""
    industries_data = [industry.dict() for industry in industries]
    count = await industry_crud.bulk_insert_industries_optimized(db, industries_data, batch_size)
    
    return IndustryResponse(
        success=True,
        message=f"批量插入成功，共插入 {count} 条记录",
        count=count
    )

@router.post("/bulk-hierarchy/", response_model=IndustryResponse)
async def bulk_insert_industries_hierarchy(
    industries: List[dict],
    batch_size: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """批量插入行业数据（支持层级结构）"""
    count = await industry_crud.bulk_insert_industries_with_hierarchy(db, industries, batch_size)
    
    return IndustryResponse(
        success=True,
        message=f"批量插入成功，共插入 {count} 条记录",
        count=count
    )

@router.get("/search/", response_model=List[Industry])
async def search_industries(
    keyword: str = Query(..., min_length=1, max_length=50),
    db: AsyncSession = Depends(get_db)
):
    """搜索行业"""
    from sqlalchemy import or_
    
    query = db.query(Industry).filter(
        or_(
            Industry.name.ilike(f"%{keyword}%"),
            Industry.pinyin.ilike(f"%{keyword}%"),
            Industry.first_char.ilike(f"%{keyword}%")
        )
    )
    
    return await query.all()
