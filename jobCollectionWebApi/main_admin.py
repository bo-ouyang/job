from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from middleware.security_middleware import SecurityHeadersMiddleware, WAFMiddleware
from contextlib import asynccontextmanager
import uvicorn
import os
import sys

# Ensure project root is in python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(project_root)
sys.path.insert(0, project_root)

import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import settings
from common.databases.PostgresManager import db_manager
from common.databases.models.system_config import SystemConfig
from services.ai_access_service import ai_access_service
from sqlalchemy import select

# Import all models to ensure they are registered for Admin
from common.databases.models import user, job, company, resume, favorite


async def _bootstrap_admin_configs() -> None:
    seed_configs = {
        "analysis_skill_noise_exact": {
            "category": "analysis",
            "description": "Exact skill tags to exclude in analysis charts",
            "value": '["\\u5176\\u4ed6","\\u5176\\u5b83","\\u4e0d\\u9650","\\u65e0","\\u6682\\u65e0"]',
        },
        "analysis_skill_noise_contains": {
            "category": "analysis",
            "description": "Keyword contains rules to exclude noisy skill tags",
            "value": (
                '["\\u4e0d\\u63a5\\u53d7\\u5c45\\u5bb6\\u529e\\u516c","\\u5c45\\u5bb6\\u529e\\u516c",'
                '"\\u8fdc\\u7a0b\\u529e\\u516c","\\u53cc\\u4f11","\\u4e94\\u9669","\\u793e\\u4fdd"]'
            ),
        },
    }

    async with db_manager.async_session() as session:
        created_products = await ai_access_service.ensure_pricing_products(session)

        stmt = select(SystemConfig.key).where(SystemConfig.key.in_(list(seed_configs.keys())))
        existing_keys = set((await session.execute(stmt)).scalars().all())
        created_configs = 0
        for key, payload in seed_configs.items():
            if key in existing_keys:
                continue
            session.add(
                SystemConfig(
                    key=key,
                    value=payload["value"],
                    category=payload["category"],
                    description=payload["description"],
                    is_active=True,
                )
            )
            created_configs += 1

        if created_configs > 0:
            await session.commit()

    if created_products or created_configs:
        print(
            f"Admin bootstrap complete: created_products={created_products}, "
            f"created_configs={created_configs}"
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Admin Service Lifespan"""
    await db_manager.initialize()
    
    if not await db_manager.health_check():
        raise RuntimeError("Database connection failed on startup")

    await _bootstrap_admin_configs()
    
    print("Admin Service: Database connection established")
    yield
    await db_manager.close()
    print("Admin Service: Shutdown complete")

app = FastAPI(
    title="招聘平台后台管理系统",
    description="独立的后台管理服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 中间件 (后台可以放开但安全头一定要加)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 新增：HTTP 防护头识别与框架版本隐藏中间件 (应尽早执行)
app.add_middleware(SecurityHeadersMiddleware)

# 新增：防范简单特征的 SQLi 与 XSS WAF 中间件
app.add_middleware(WAFMiddleware)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Admin Setup
from admin import setup_admin
setup_admin(app, db_manager.engine)

@app.get("/")
async def root():
    return {"message": "Admin Panel Service Running. Go to /admin"}

if __name__ == "__main__":
    uvicorn.run(
        "main_admin:app",
        host="127.0.0.1",
        port=8001,
        log_level=settings.LOG_LEVEL.lower(),
        reload=True,
        reload_dirs=["./core", "./common"],
    )
