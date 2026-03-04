# app/schemas.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# 城市相关模式
class CityBase(BaseModel):
    code: int
    name: str
    tip: Optional[str] = None
    first_char: Optional[str] = None
    pinyin: Optional[str] = None
    rank: Optional[int] = 0
    mark: Optional[int] = 0
    position_type: Optional[int] = 0
    city_type: Optional[int] = None
    capital: Optional[int] = 0
    color: Optional[str] = None
    recruitment_type: Optional[str] = None
    city_code: Optional[str] = None
    region_code: Optional[int] = None
    center_geo: Optional[str] = None
    value: Optional[str] = None
    parent_id: Optional[int] = None
    level: Optional[int] = 0

class CityCreate(CityBase):
    pass

class CityUpdate(CityBase):
    pass

class City(CityBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True



# API 响应模式
class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    count: Optional[int] = 0
