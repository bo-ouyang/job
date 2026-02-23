from starlette_admin import CustomView
from common.databases.PostgresManager import db_manager
from sqlalchemy import func, select
from common.databases.models.user import User, UserRole
from common.databases.models.job import Job
from common.databases.models.company import Company
from common.databases.models.resume import Resume
import os
import psutil
import platform
import sys

class HomeView(CustomView):
    async def render(self, request, templates):
        # Fetch stats
        async with db_manager.async_session() as session:
            # Helper to count
            async def get_count(model):
                stmt = select(func.count(model.id))
                result = await session.execute(stmt)
                return result.scalar()

            user_count = await get_count(User)
            job_count = await get_count(Job)
            company_count = await get_count(Company)
            resume_count = await get_count(Resume)
            
        stats = {
            "user_count": user_count,
            "job_count": job_count,
            "company_count": company_count,
            "resume_count": resume_count
        }

        # System Status (Admin Only)
        system_status = None
        user_role = getattr(request.state, "user_role", None)
        
        if user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # DB Pool Status for Async Engine
            # accessing pool on async engine is slightly different
            pool = db_manager.engine.sync_engine.pool
            
            system_status = {
                "platform": platform.platform(),
                "python_version": sys.version.split()[0],
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_total": f"{mem.total / (1024**3):.2f} GB",
                "memory_used": f"{mem.used / (1024**3):.2f} GB",
                "memory_percent": mem.percent,
                "disk_total": f"{disk.total / (1024**3):.2f} GB",
                "disk_percent": disk.percent,
                # DB Stats
                "db_pool_size": pool.size(),
                "db_checked_in": pool.checkedin(),
                "db_checked_out": pool.checkedout(),
                "db_overflow": pool.overflow(),
            }
        
        return templates.TemplateResponse(
            "admin/dashboard.html", 
            {
                "request": request, 
                "stats": stats, 
                "system_status": system_status,
                "env": os.getenv("ENVIRONMENT", "dev")
            }
        )
