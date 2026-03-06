import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.sql import text
from jobCollectionWebApi.core.logger import sys_logger as logger
from jobCollectionWebApi.config import settings


class PostgresManager:
    """PostgreSQL database manager."""

    def __init__(self):
        self.async_session = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

        self.engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.POSTGRES_POOL_MIN_SIZE,
            max_overflow=settings.POSTGRES_POOL_MAX_SIZE
            - settings.POSTGRES_POOL_MIN_SIZE,
            pool_pre_ping=getattr(settings, "POSTGRES_POOL_PRE_PING", True),
            pool_recycle=getattr(settings, "POSTGRES_POOL_RECYCLE", 3600),
            echo=settings.DEBUG,
        )

    async def _ensure_ai_task_schema(self, conn):
        """
        Backward-compatible schema guard:
        ensure ai_tasks.analysis_input exists in environments without migrations.
        """
        try:
            table_stmt = text("SELECT to_regclass('public.ai_tasks')")
            table_name = (await conn.execute(table_stmt)).scalar()
            if table_name:
                await conn.execute(
                    text(
                        "ALTER TABLE ai_tasks "
                        "ADD COLUMN IF NOT EXISTS analysis_input JSONB"
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to ensure ai_tasks.analysis_input column: {e}")

    async def initialize(self):
        """Initialize database connection."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                self.async_session = async_sessionmaker(
                    self.engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                )

                async with self.engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                    await self._ensure_ai_task_schema(conn)

                self._initialized = True
                # await self.create_tables()
                logger.info("PostgreSQL connection initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL connection: {e}")
                raise

    async def get_session(self):
        """Return a database session object."""
        if not self._initialized:
            await self.initialize()

        return self.async_session()

    async def close(self):
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            self._initialized = False
            logger.info("PostgreSQL connection closed")

    async def get_db(self):
        """Yield a database session for dependency injection."""
        if not self._initialized:
            await self.initialize()

        session = self.async_session()
        try:
            yield session
        finally:
            await session.close()

    async def health_check(self) -> bool:
        """Database health check."""
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            return False

    async def create_tables(self):
        """Create all tables."""
        from .models.base import Base

        try:
            from .models import (
                user,
                job,
                company,
                industry,
                payment,
                product,
                spider_boss_crawl_url,
                wallet,
                resume,
                application,
                message,
                favorite,
                admin_log,
                analysis,
                city,
                fetch_failure,
                school,
                school_special,
                school_special_intro,
                skills,
                system_config,
                boss_spider_filter,
                boss_crawl_task,
                proxy,
                ai_task,
            )

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("All database tables created successfully")
        except ImportError as e:
            logger.warning(
                "Skipping table creation due to import error "
                f"(likely circular or missing deps): {e}"
            )
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")


# Keep exported variable name for compatibility.
db_manager = PostgresManager()
