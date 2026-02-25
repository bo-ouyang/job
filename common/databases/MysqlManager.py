import sys,os
import asyncio
project_root = os.path.dirname(os.path.curdir)
print(project_root)
sys.path.insert(0, project_root)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.sql import text
from jobCollectionWebApi.core.logger import sys_logger as logger
from jobCollectionWebApi.config import settings


class MySQLManager:
    """数据库管理器"""
    
    def __init__(self):
        self.async_session = None
        self._initialized = False
        
        # 创建异步引擎 (Sync operation, safe in init)
        self.engine = create_async_engine(
            settings.MYSQL_URL,
            pool_size=settings.MYSQL_POOL_MIN_SIZE,
            max_overflow=settings.MYSQL_POOL_MAX_SIZE - settings.MYSQL_POOL_MIN_SIZE,
            pool_recycle=settings.MYSQL_POOL_RECYCLE,
            pool_pre_ping=settings.MYSQL_POOL_PRE_PING,
            echo=settings.MYSQL_POOL_ECHO,
            connect_args={
                "connect_timeout": settings.MYSQL_CONNECT_TIMEOUT,
                #"read_timeout": settings.MYSQL_READ_TIMEOUT,
                #"write_timeout": settings.MYSQL_WRITE_TIMEOUT,
            }
        )
        
    async def initialize(self):
        """初始化数据库连接"""
        if self._initialized:
            return
        
        try:
            # Engine created in __init__
            
            # 创建会话工厂
            
            # 创建会话工厂
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=settings.MYSQL_EXPIRE_ON_COMMIT,
                autoflush=settings.MYSQL_AUTOFLUSH,
                #autocommit=settings.MYSQL_AUTOCOMMIT
            )
            
            # 测试连接
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            
            self._initialized = True
            await self.create_tables()
            logger.info("MySQL connection initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize MySQL connection: {e}")
            raise
    
    async def get_session(self):
        """获取数据库会话（返回会话对象）"""
        await self.initialize()
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        return self.async_session()
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            logger.info("MySQL connection closed")
    
    async def get_db(self):
        """获取数据库会话（用于依赖注入）"""
        if not self._initialized:
            await self.initialize()
        
        session = self.async_session()
        try:
            yield session
        finally:
            await session.close()
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"MySQL health check failed: {e}")
            return False
    
    async def create_tables(self):
        """创建所有表"""
        from .models.base import Base
        # Import all models to ensure they are registered with Base.metadata
        from .models import (
            user, job, company, industry, payment, product, spider_boss_crawl_url,
            wallet, resume, application, message, favorite, admin_log, analysis,
            city, fetch_failure, major_job_map, school, school_special, school_special_intro,skills,
            boss_spider_filter, boss_crawl_task
        )
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("All database tables created successfully")


db_manager = MySQLManager()
# async def main():
    

#     #db_manager = MySQLManager()
#     await db_manager.create_tables()
    
    
# async def main():
#     pass

# if __name__ == '__main__':
#     asyncio.run(main())
