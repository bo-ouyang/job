import sys,os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.sql import text
from jobCollectionWebApi.core.logger import sys_logger as logger
from jobCollectionWebApi.config import settings


class PostgresManager:
    """PostgreSQL 数据库管理器"""
    
    def __init__(self):
        self.async_session = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # 创建异步引擎
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.POSTGRES_POOL_MIN_SIZE,
            max_overflow=settings.POSTGRES_POOL_MAX_SIZE - settings.POSTGRES_POOL_MIN_SIZE,
            pool_pre_ping=getattr(settings, 'POSTGRES_POOL_PRE_PING', True),
            pool_recycle=getattr(settings, 'POSTGRES_POOL_RECYCLE', 3600),
            echo=settings.DEBUG, # 开发模式下开启回显
        )
    async def initialize(self):
        """初始化数据库连接"""
        if self._initialized:
            return
            
        async with self._init_lock:
            if self._initialized:
                return
                
            try:
                # 创建会话工厂
                self.async_session = async_sessionmaker(
                    self.engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False # 默认关闭自动刷新，手动控制
                )
                
                # 测试连接
                async with self.engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                
                self._initialized = True
                await self.create_tables()
                logger.info("PostgreSQL connection initialized successfully")
                
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL connection: {e}")
                raise
    async def get_session(self):
        """获取数据库会话（返回会话对象）"""
        if not self._initialized:
            await self.initialize()
        
        return self.async_session()
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            logger.info("PostgreSQL connection closed")
    
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
            logger.error(f"PostgreSQL health check failed: {e}")
            return False
    
    async def create_tables(self):
        """创建所有表"""
        from .models.base import Base
        # Import all models to ensure they are registered with Base.metadata
        # 注意: 这里的导入路径可能需要根据实际项目结构微调
        # 假设 MysqlManager 中的导入是正确的，我们保持一致
        try:
            from .models import (
                user, job, company, industry, payment, product, spider_boss_crawl_url,
                wallet, resume, application, message, favorite, admin_log, analysis,
                city, fetch_failure, school, school_special, school_special_intro, skills, system_config,
                boss_spider_filter, boss_crawl_task, proxy, ai_task
            )
            
            async with self.engine.begin() as conn:
                 # 确保使用 PostgreSQL 方言特性 (如果用到 JSONB 等)
                await conn.run_sync(Base.metadata.create_all)
            logger.info("All database tables created successfully")
        except ImportError as e:
            logger.warning(f"Skipping table creation due to import error (likely circular or missing deps): {e}")
        except Exception as e:
             logger.error(f"Failed to create tables: {e}")

# 实例化并导出 (保持变量名 db_manager 以最小化代码变动)
db_manager = PostgresManager()
