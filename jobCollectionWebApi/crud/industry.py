# jobCollectionWebApi/crud/industry.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, and_
from typing import Optional, List, Dict, Any
from common.databases.models.industry import Industry
from common.databases.PostgresManager import db_manager
from datetime import datetime
import time

from sqlalchemy import select, text
from core.logger import sys_logger as logger


class IndustryCRUD:
    
    async def get_industry(self, db: AsyncSession, industry_id: int):
        """根据ID获取行业"""
        result = await db.execute(select(Industry).filter(Industry.id == industry_id))
        return result.scalar_one_or_none()
    
    async def get_industry_by_code(self, db: AsyncSession, code: int):
        """根据编码获取行业"""
        result = await db.execute(select(Industry).filter(Industry.code == code))
        return result.scalar_one_or_none()
    
    async def get_industries(self, db: AsyncSession, skip: int = 0, limit: int = 100):
        """获取行业列表"""
        result = await db.execute(
            select(Industry).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    async def get_industries_by_level(self, db: AsyncSession, level: int):
        """根据层级获取行业"""
        result = await db.execute(
            select(Industry).filter(Industry.level == level)
        )
        return result.scalars().all()
    
    async def get_children_industries(self, db: AsyncSession, parent_id: int):
        """获取子行业"""
        result = await db.execute(
            select(Industry).filter(Industry.parent_id == parent_id)
        )
        return result.scalars().all()
    
    async def get_industry_tree(self, db: AsyncSession, parent_id: Optional[int] = None):
        """获取行业树形结构"""
        if parent_id is None:
            # 获取所有一级行业
            stmt = select(Industry).filter(Industry.level == 0)
        else:
            # 获取指定父级的子行业
            stmt = select(Industry).filter(Industry.parent_id == parent_id)
        
        result = await db.execute(stmt)
        root_industries = result.scalars().all()
        
        result_list = []
        for industry in root_industries:
            industry_dict = industry.to_dict()
            # 递归获取子行业
            children = await self.get_industry_tree(db, industry.id)
            if children:
                industry_dict['children'] = children
            result_list.append(industry_dict)
        
        return result_list
    
    async def upsert_industry(self, db: AsyncSession, industry_data: Dict[str, Any]):
        """插入或更新行业数据"""
        db_industry = await self.get_industry_by_code(db, industry_data["code"])
        
        if db_industry:
            # 更新现有记录
            for key, value in industry_data.items():
                if hasattr(db_industry, key) and value is not None:
                    setattr(db_industry, key, value)
            db_industry.updated_at = datetime.now()
        else:
            # 创建新记录
            industry_data["created_at"] = datetime.now()
            industry_data["updated_at"] = datetime.now()
            db_industry = Industry(**industry_data)
            db.add(db_industry)
        
        db.commit()
        db.refresh(db_industry)
        return db_industry
    
    async def delete_industry(self, db: AsyncSession, industry_id: int):
        """删除行业"""
        db_industry = await self.get_industry(db, industry_id)
        if db_industry:
            db.delete(db_industry)
            db.commit()
        return db_industry
    
    async def bulk_insert_industries_optimized(
        self, 
        db: AsyncSession, 
        industries_data: List[Dict[str, Any]], 
        batch_size: int = 100
    ) -> int:
        """
        批量插入行业数据（优化版本）
        
        Args:
            db: 数据库会话
            industries_data: 行业数据列表
            batch_size: 每批插入的数量
            
        Returns:
            插入的记录数
        """
        total_inserted = 0
        
        try:
            # 分批处理
            for i in range(0, len(industries_data), batch_size):
                batch = industries_data[i:i + batch_size]
                industries = []
                
                for data in batch:
                    # 数据验证和清理
                    cleaned_data = self._clean_industry_data(data)
                    cleaned_data["created_at"] = datetime.now()
                    cleaned_data["updated_at"] = datetime.now()
                    industry = Industry(**cleaned_data)
                    industries.append(industry)
                
                db.add_all(industries)
                await db.commit()
                
                
                total_inserted += len(industries)
                logger.info(f"第 {i//batch_size + 1} 批插入成功，共 {len(industries)} 条记录")
                
                # 小延迟避免数据库压力
                if i + batch_size < len(industries_data):
                    time.sleep(0.1)
            
            print(f"批量插入完成，总计 {total_inserted} 条记录")
            return total_inserted
            
        except Exception as e:
            await db.rollback()
            print(f"批量插入失败: {e}")
            raise
    
    async def bulk_insert_industries_with_hierarchy(
        self, 
        db: AsyncSession, 
        industries_data: List[Dict[str, Any]], 
        batch_size: int = 100
    ) -> int:
        """
        批量插入行业数据（支持层级结构）
        
        Args:
            db: 数据库会话
            industries_data: 行业数据列表（包含subLevelModelList）
            batch_size: 每批插入的数量
            
        Returns:
            插入的记录数
        """
        total_inserted = 0
        
        try:
            # 处理行业数据（可能包含嵌套结构）
            flat_industries = []
            
            for industry_data in industries_data:
                # 处理父级行业
                parent_data = self._extract_industry_data(industry_data)
                parent_data["level"] = 0
                parent_data["parent_id"] = None
                flat_industries.append(parent_data)
                
                # 处理子行业
                sub_industries = industry_data.get("subLevelModelList", [])
                if sub_industries:
                    for sub_data in sub_industries:
                        child_data = self._extract_industry_data(sub_data)
                        child_data["level"] = 1
                        child_data["parent_id"] = parent_data["code"]  # 使用code作为临时引用
                        flat_industries.append(child_data)
            
            # 第一阶段：插入所有行业，parent_id设为NULL
            logger.info("第一阶段：插入所有行业（parent_id设为NULL）")
            for i in range(0, len(flat_industries), batch_size):
                batch = flat_industries[i:i + batch_size]
                industries = []
                
                for data in batch:
                    cleaned_data = self._clean_industry_data(data)
                    # 第一阶段先不设置parent_id
                    cleaned_data["parent_id"] = None
                    cleaned_data["created_at"] = datetime.now()
                    cleaned_data["updated_at"] = datetime.now()
                    industry = Industry(**cleaned_data)
                    industries.append(industry)
                
                db.add_all(industries)
                await db.commit()
                total_inserted += len(industries)
                logger.info(f"第 {i//batch_size + 1} 批插入成功，共 {len(industries)} 条记录")
                
                if i + batch_size < len(flat_industries):
                    time.sleep(0.1)
            
            # 第二阶段：更新parent_id
            logger.info("第二阶段：更新parent_id")
            await self._update_parent_ids(db, flat_industries)
            
            print(f"批量插入完成，总计 {total_inserted} 条记录")
            return total_inserted
            
        except Exception as e:
            await db.rollback()
            print(f"批量插入失败: {e}")
            raise
    
    async def _update_parent_ids(self, db: AsyncSession, industries_data: List[Dict[str, Any]]):
        """更新父级ID"""
        try:
            # 先查询所有行业的id和code映射
            from sqlalchemy import text
            result = await db.execute(text("SELECT id, code FROM industries"))
            code_to_id = {row[1]: row[0] for row in result.fetchall()}
            
            # 更新父级ID
            for data in industries_data:
                code = data.get('code')
                parent_code = data.get('parent_id')
                
                if parent_code and parent_code in code_to_id:
                    # 更新父级ID
                    stmt = text("""
                        UPDATE industries 
                        SET parent_id = :parent_id 
                        WHERE code = :code
                    """)
                    await db.execute(
                        stmt, 
                        {"parent_id": code_to_id[parent_code], "code": code}
                    )
            
            await db.commit()
            logger.info("父级ID更新完成")
            
        except Exception as e:
            await db.rollback()
            raise
    async def get_rollup_codes(self, db: AsyncSession, codes: List[int]) -> List[int]:
        if not codes: return []
        
        # 使用递归 CTE 向上查找直到 level=1
        stmt = text("""
            WITH RECURSIVE industry_tree AS (
                -- Base case: select starting nodes
                SELECT code, parent_id, level
                FROM industries
                WHERE code = ANY(:codes) OR parent_id = ANY(:codes)
                
                UNION ALL
                
                -- Recursive step: join with parents
                SELECT i.code, i.parent_id, i.level
                FROM industries i
                INNER JOIN industry_tree it ON i.code = it.parent_id
            )
            SELECT code FROM industry_tree WHERE level <= 1;
        """)
        
        result = await db.execute(stmt, {"codes": codes})
        return result.scalars().all()

    # async def get_rollup_codes(self, db: AsyncSession, codes: List[int]) -> List[int]:
        # """
        # 1. 找到 industry 表中 code 在 codes 中，或者 parent_id 在 codes 中的数据。
        # 2. 如果数据的 level != 1，则继续查找父级 id，直到 level = 1 (或到达根部 level 0)。
        # """
        # if not codes:
        #     return []
            
        # all_resolved_codes = set()
        # all_resolved_codes.update(codes)
        # # 1. 查找匹配 code 或 parent_id 的初始集合
        # stmt = select(Industry).where(or_(
        #     Industry.code.in_(codes),
        #     Industry.parent_id.in_(codes)
        # ))
        # res = await db.execute(stmt)
        # initial_items = res.scalars().all()
        
        # to_resolve = set()
        # for item in initial_items:
        #     if item.level == 1:
        #         all_resolved_codes.add(item.code)
        #     elif item.parent_id:
        #         to_resolve.add(item.parent_id)
        # # 2. 向上递归直到 level 1 
        # visited = set()
        # while to_resolve:
        #     to_resolve = to_resolve - visited
        #     if not to_resolve:
        #         break
        #     visited.update(to_resolve)
        #     stmt = select(Industry).where(Industry.code.in_(list(to_resolve)))
        #     res = await db.execute(stmt)
        #     items = res.scalars().all()
            
        #     next_to_resolve = set()
        #     for item in items:
        #         if item.level == 1:
        #             all_resolved_codes.add(item.code)
        #         elif item.parent_id:
        #             next_to_resolve.add(item.parent_id)
        #     to_resolve = next_to_resolve
        # return list(all_resolved_codes)

    def _extract_industry_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """提取行业数据"""
        return {
            "code": data.get("code"),
            "name": data.get("name"),
            "tip": data.get("tip"),
            "first_char": data.get("firstChar"),
            "pinyin": data.get("pinyin"),
            "rank": data.get("rank", 0),
            "mark": data.get("mark", 0),
            "position_type": data.get("positionType", 0),
            "city_type": data.get("cityType"),
            "capital": data.get("capital", 0),
            "color": data.get("color"),
            "recruitment_type": data.get("recruitmentType"),
            "city_code": data.get("cityCode"),
            "region_code": data.get("regionCode"),
            "center_geo": data.get("centerGeo"),
            "value": data.get("value"),
            "level": data.get("level", 0),
            "parent_id": data.get("parentId")
        }
    
    def _clean_industry_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理行业数据，确保数据类型正确
        
        Args:
            data: 原始行业数据
            
        Returns:
            清理后的行业数据
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

industry = IndustryCRUD()
