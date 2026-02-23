from fastapi import FastAPI
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

# Import all models to ensure they are registered for Admin
from common.databases.models import user, job, company, resume, favorite

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Admin Service Lifespan"""
    await db_manager.initialize()
    
    if not await db_manager.health_check():
        raise RuntimeError("Database connection failed on startup")
    
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
