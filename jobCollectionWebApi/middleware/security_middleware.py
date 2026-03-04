import re
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json
from core.logger import sys_logger as logger
from core.exceptions import AppException
from core.status_code import StatusCode
from fastapi.responses import JSONResponse

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    HTTP 防护头中间件
    添加防御 XSS、点击劫持、MIME嗅探 等安全响应头，并抹除框架指纹
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # 移除可能暴露服务器类型和版本的 HTTP 头 (如 Server: uvicorn)
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]
            
        # 强制添加自定义占位符掩盖指纹
        response.headers["Server"] = "OceanServer"
            
        # 防止浏览器猜测资源类型 (MIME 嗅探防御)
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 开启浏览器的 XSS 过滤功能，并在检测到攻击时阻止页面渲染
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # 拒绝被嵌入到外部站点的 iframe 中，防止点击劫持
        response.headers["X-Frame-Options"] = "DENY"
        
        # 强制客户端通过 HTTPS 访问 (HSTS, 一年内有效)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # 防止跨域策略泄露 Referrer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 限制可以执行的脚本源 (初步版本，限制过于严格可能导致 Vue/React 出错，先设定基础自保)
        # 如果前端出现静态资源被 block，可以注释掉下面这行
        # response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';"
        
        return response

class WAFMiddleware(BaseHTTPMiddleware):
    """
    基础 Web 应用防火墙中间件 (WAF)
    针对常见的 SQL 注入特征词和 XSS 特征进行粗略拦截
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        
        # SQL 注入危险探针正则式 (忽略大小写)
        # 例如匹配: ' or 1=1 , union select , drop table
        self.sql_injection_pattern = re.compile(
            r"(?i)(\b(select|update|delete|insert|drop|alter|truncate|union|declare|exec)\b(?:.+?(?:;|\binto\b|\bfrom\b)))|"
            r"('|%27)\s*(OR|AND)\s*(?:\d+=\d+|'[^']*'='[^']*')", 
            re.IGNORECASE
        )
        
        # XSS 危险探针正则式
        self.xss_pattern = re.compile(
            r"(?i)(<script.*?>.*?</script>|"
            r"javascript:|vbscript:|expression\(|"
            r"onload=|onerror=|onmouseover=|onclick=|onfocus=)", 
            re.IGNORECASE
        )

    def _is_malicious(self, content: str) -> bool:
        if not content:
            return False
        if self.sql_injection_pattern.search(content):
            return True
        if self.xss_pattern.search(content):
            return True
        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. 检测 Query 参数
        query_string = request.url.query.lower()
        if self._is_malicious(query_string):
            logger.warning(f"WAF Intercepted malicious query from IP: {request.client.host} - Query: {query_string}")
            return JSONResponse(
                status_code=403,
                content={"code": StatusCode.FORBIDDEN, "msg": "Access Denied: Malicious Request Detected.", "data": None}
            )
            
        # 注意: 拦截 Body 比较吃性能，而且 FastAPI 消费 body 后需要恢复。
        # 这里的 WAF 仅针对由于长字符串造成的 Query Get 攻击进行低成本拦截。
        # POST 请求的强类型约束主要依赖 Pydantic Models 拦截。
        
        response = await call_next(request)
        return response
