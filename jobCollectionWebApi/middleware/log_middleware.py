import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from crud.analysis import api_log
from schemas.analysis import APILogCreate
from common.databases.PostgresManager import db_manager
from core.logger import sys_logger as logger

class APILogMiddleware(BaseHTTPMiddleware):
    """
    接口访问日志中间件
    用于记录 QPS、响应耗时、状态码等统计数据
    """
    async def dispatch(self, request: Request, call_next):
        # 排除非 API 请求或健康检查
        if request.url.path.startswith("/static") or request.url.path in ["/health", "/", "/favicon.ico"]:
            return await call_next(request)

        start_time = time.time()
        
        # 继续执行请求链
        response = await call_next(request)
        
        process_time = time.time() - start_time
        
        # 将每个成功的路由访问都输出在应用滚动文本日志中，接替刚才 Uvicorn 的 Access Log
        logger.info(
            f"{request.client.host} - \"{request.method} {request.url.path}\" "
            f"{response.status_code} - {round(process_time*1000, 2)}ms"
        )
        
        # 异步记录到数据库
        # 注意：此处使用新的 session 避免干扰主流程事务
        try:
            async with db_manager.async_session() as db:
                # 尝试获取用户ID (如果已在其他地方存入 request.state)
                # 提示：鉴权通常在路由层发生，中间件可能拿不到 user 对象
                user_id = getattr(request.state, "user_id", None)
                
                log_data = APILogCreate(
                    path=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    process_time=round(process_time, 4),
                    user_id=user_id,
                    ip_address=request.client.host,
                    user_agent=request.headers.get("user-agent")
                )
                await api_log.create(db, obj_in=log_data)
                # 重要：BaseHTTPMiddleware 中需要手动 commit，因为我们开了新 session
                await db.commit()
        except Exception as e:
            # 记录日志过程中的错误不应中断业务返回
            logger.error(f"APILogMiddleware error: {e}")
            
        return response
