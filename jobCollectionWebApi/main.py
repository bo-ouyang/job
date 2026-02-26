from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(project_root)
sys.path.insert(0, project_root)

import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import settings
from common.databases.PostgresManager import db_manager
# Import models to ensure they are registered with Base.metadata
from common.databases.models import user, job, company, resume, favorite
from api.v1.api import api_router
from core.logger import sys_logger as logger
from middleware.log_middleware import APILogMiddleware
#from common.search.conn import es_manager


    
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库连接
    await db_manager.initialize()
    #await db_manager.create_tables()
    
    # 检查数据库连接
    if not await db_manager.health_check():
        logger.error("Database connection failed on startup")
        raise RuntimeError("Database connection failed on startup")
    
    logger.success("Database connection established successfully")
    
    # 初始化并检查 ES 连接
    # if await es_manager.health_check():
    #     logger.success("Elasticsearch connection established successfully")
    # else:
    #     logger.warning("Elasticsearch connection failed on startup, some features may be unavailable")
    
    # Start Redis Listener for WebSocket
    from api.v1.endpoints.ws_controller import manager, start_redis_listener
    redis_task = asyncio.create_task(start_redis_listener(manager))
    logger.info("Redis Sub/Pub Listener started for WebSockets.")

    yield  # 应用运行期间
    
    # Cancel Redis Listener
    redis_task.cancel()
    
    # 关闭时清理资源
    await db_manager.close()
    logger.info("Application shutdown complete")

app = FastAPI(
    title="求职技能分析平台 API",
    description="基于 FastAPI 的 Python 岗位技能需求分析系统",
    version="1.0.0",
    #openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 全局日志中间件
app.add_middleware(APILogMiddleware)

from middleware.response_middleware import UnifiedResponseMiddleware
app.add_middleware(UnifiedResponseMiddleware)

from core.status_code import StatusCode
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 全局异常处理
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "msg": exc.detail, # 修复：不再强转 str，如果里头是字典就能被原样返回
            "data": None
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=StatusCode.UNPROCESSABLE_ENTITY,
        content={
            "code": StatusCode.UNPROCESSABLE_ENTITY,
            "msg": "请求参数验证失败",
            "data": exc.errors() # 修复：直接暴露 Pydantic 解析后的 List[Dict] 而不是长字符串
        },
    )

from sqlalchemy.exc import SQLAlchemyError, IntegrityError

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request, exc):
    logger.exception("Database error (Captured by Loguru):")
    if isinstance(exc, IntegrityError):
        return JSONResponse(
            status_code=StatusCode.CONFLICT,
            content={
                "code": StatusCode.CONFLICT,
                "msg": "数据发生冲突(如重复的数据、邮箱已存在等)",
                "data": str(exc.orig) if hasattr(exc, "orig") else str(exc)
            },
        )
    return JSONResponse(
        status_code=StatusCode.INTERNAL_SERVER_ERROR,
        content={
            "code": StatusCode.INTERNAL_SERVER_ERROR,
            "msg": "数据库内部错误",
            "data": str(exc) if settings.DEBUG else None
        },
    )
    
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("服务器内部错误 (Captured by Loguru):")
    return JSONResponse(
        status_code=StatusCode.INTERNAL_SERVER_ERROR,
        content={
            "code": StatusCode.INTERNAL_SERVER_ERROR,
            "msg": "服务器内部错误",
            "data": str(exc) if settings.DEBUG else None
        },
    )

from fastapi.staticfiles import StaticFiles

# 包含 API 路由
app.include_router(api_router, prefix=settings.API_V1_STR)

# 挂载静态文件目录
# 确保目录存在
static_dir = os.path.join(project_root, "static")
# --- Admin Panel (Starlette-Admin) ---
# Moved to main_admin.py (Port 8001)
# from core.admin import setup_admin
# setup_admin(app, db_manager.engine)

@app.get("/")
async def root():
    return {"message": "求职技能分析平台 API"}

@app.get("/health")
async def health_check():
    """健康检查接口"""
    db_health = await db_manager.health_check()
    #es_health = await es_manager.health_check()
    
    return {
        "status": "healthy" if db_health else "degraded",
        "database": "connected" if db_health else "disconnected",
        "environment": settings.ENVIRONMENT
    }


if __name__ == "__main__":
    logger.info(f"Starting server with Uvicorn on 127.0.0.1:8000...")
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_config=None,  # !!! 禁用 Uvicorn 原生的纯文本日志配置，强迫它被我们刚才接管 !!!
        reload_dirs=["."],
        reload_excludes=["./tests/*", "./logs/*"],
        reload_delay=0.5,
        access_log=False, # 防止 Uvicorn 疯狂刷 Access 阻碍我们排错，可以在 Loguru 这边处理或靠 Middleware 打印
    )
