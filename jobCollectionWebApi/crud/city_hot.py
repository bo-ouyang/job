# app/crud.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, and_, select
from typing import Optional, List, Dict, Any
from common.databases.models.city_hot import CityHot
from common.databases.PostgresManager import db_manager
from datetime import datetime
import time
# 城市 CRUD
class CityHotCRUD:
    
    async def get_city_hot(self, db: AsyncSession, city_id: int):
        result = await db.execute(select(CityHot).filter(CityHot.id == city_id))
        return result.scalars().first()
    
    async def get_city_hot_by_code(self, db: AsyncSession, code: int):
        result = await db.execute(select(CityHot).filter(CityHot.code == code))
        return result.scalars().first()
    
    async def get_city_hots(self, db: AsyncSession, skip: int = 0, limit: int = 100):
        result = await db.execute(select(CityHot).offset(skip).limit(limit))
        return result.scalars().all()
    
    async def get_city_hots_by_level(self, db: AsyncSession, level: int):
        result = await db.execute(select(CityHot).where(CityHot.level == level))
        return result.scalars().all()
    
    async def get_children_city_hots(self, db: AsyncSession, parent_id: int):
        result = await db.execute(select(CityHot).where(CityHot.parent_id == parent_id))
        return result.scalars().all()
    
    

    
    async def upsert_city(self, db: AsyncSession, city_data: Dict[str, Any]):
        """插入或更新城市数据"""
        db_city = await self.get_city_by_code(db, city_data["code"])
        
        if db_city:
            # 更新现有记录
            for key, value in city_data.items():
                if hasattr(db_city, key) and value is not None:
                    setattr(db_city, key, value)
            db_city.updated_at = datetime.now()
        else:
            # 创建新记录
            db_city = City(**city_data)
            db.add(db_city)
        
        await db.commit()
        await db.refresh(db_city)
        return db_city
    
    async def delete_city(self, db: AsyncSession, city_id: int):
        db_city = await self.get_city(db, city_id)
        if db_city:
            await db.delete(db_city)
            await db.commit()
        return db_city
    async def bulk_insert_cities_optimized(self,db: AsyncSession, cities_data: List[Dict[str, Any]], batch_size: int = 100) -> int:
        """
        批量插入城市数据（方法2：分批插入，优化性能）
        
        Args:
            db: 数据库会话
            cities_data: 城市数据列表
            batch_size: 每批插入的数量
            
        Returns:
            插入的记录数
        """
        total_inserted = 0
        #session = db_manager.get_session()
        try:
            # 分批处理
            for i in range(0, len(cities_data), batch_size):
                batch = cities_data[i:i + batch_size]
                cities = []
                
                for data in batch:
                    # 数据验证和清理
                    cleaned_data = CityCRUD._clean_city_data(data)
                    city = City(**cleaned_data)
                    cities.append(city)
                
                db.add_all(cities)
                await db.commit()
                
                total_inserted += len(cities)
                print(f"第 {i//batch_size + 1} 批插入成功，共 {len(cities)} 条记录")
                
                # 小延迟避免数据库压力
                if i + batch_size < len(cities_data):
                    time.sleep(0.1)
            
            print(f"批量插入完成，总计 {total_inserted} 条记录")
            return total_inserted
            
        except Exception as e:
            
            await db.rollback()
            print(f"批量插入失败: {e}")
            raise
    
    @staticmethod
    def _clean_city_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理城市数据，确保数据类型正确
        
        Args:
            data: 原始城市数据
            
        Returns:
            清理后的城市数据
        """
        cleaned = {}
        
        for key, value in data.items():
            if value is None:
                cleaned[key] = None
            elif key in ['code', 'rank', 'mark', 'position_type', 'city_type', 
                        'capital', 'region_code', 'parent_id', 'level']:
                # 整数类型
                try:
                    cleaned[key] = int(value) if value != '' else None
                except (ValueError, TypeError):
                    cleaned[key] = None
            elif key in ['name', 'tip', 'first_char', 'pinyin', 'color', 
                        'recruitment_type', 'city_code', 'center_geo', 'value']:
                # 字符串类型
                cleaned[key] = str(value).strip() if value else None
            else:
                cleaned[key] = value
        
        return cleaned
