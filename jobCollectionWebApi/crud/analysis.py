from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from common.databases.models.analysis import AnalysisResult, UserQuery, APILog, TaskLog
from jobCollectionWebApi.schemas.analysis import (
    AnalysisResultCreate, AnalysisResultUpdate, 
    UserQueryCreate, APILogCreate,
    TaskLogCreate, TaskLogUpdate
)
from .base import CRUDBase

class CRUDAnalysisResult(CRUDBase[AnalysisResult, AnalysisResultCreate, AnalysisResultUpdate]):
    """分析结果 CRUD 操作"""
    
    async def get_latest_by_type(
        self, db: AsyncSession, analysis_type: str, *, limit: int = 10
    ) -> List[AnalysisResult]:
        """获取指定类型的最新分析结果"""
        stmt = (
            select(AnalysisResult)
            .where(AnalysisResult.analysis_type == analysis_type)
            .order_by(desc(AnalysisResult.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

analysis_result = CRUDAnalysisResult(AnalysisResult)

class CRUDUserQuery(CRUDBase[UserQuery, UserQueryCreate, UserQueryCreate]):
    """用户查询 CRUD 操作"""
    
    async def get_recent_queries(
        self, db: AsyncSession, *, limit: int = 50
    ) -> List[UserQuery]:
        """获取最近的用户查询"""
        stmt = (
            select(UserQuery)
            .order_by(desc(UserQuery.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

user_query = CRUDUserQuery(UserQuery)

class CRUDAPILog(CRUDBase[APILog, APILogCreate, APILogCreate]):
    """接口日志 CRUD 操作"""
    
    async def get_stats(self, db: AsyncSession, *, limit: int = 100) -> List[APILog]:
        """获取最近的接口日志用于数据分析"""
        stmt = select(APILog).order_by(desc(APILog.created_at)).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

api_log = CRUDAPILog(APILog)

class CRUDTaskLog(CRUDBase[TaskLog, TaskLogCreate, TaskLogUpdate]):
    """任务日志 CRUD"""
    async def get_by_task_id(self, db: AsyncSession, task_id: str) -> Optional[TaskLog]:
        stmt = select(TaskLog).where(TaskLog.task_id == task_id)
        result = await db.execute(stmt)
        return result.scalars().first()

task_log = CRUDTaskLog(TaskLog)
