from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json
from fastapi.responses import JSONResponse, Response

class UnifiedResponseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow skipping certain paths (e.g. docs, openapi, admin)
        if request.url.path.startswith("/docs") or \
           request.url.path.startswith("/redoc") or \
           request.url.path.startswith("/openapi.json") or \
           request.url.path.startswith("/admin") or \
           request.url.path.startswith("/static"):
            return await call_next(request)

        response = await call_next(request)

        # Only wrap success JSON responses (200-299)
        # Exceptions are handled by exception handlers
        if 200 <= response.status_code < 300:
            # Check content-type
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                # We need to read the response body to wrap it
                # Note: Streaming responses might be tricky, but for typical API it works
                response_body = [section async for section in response.body_iterator]
                response.body_iterator = iter(response_body)
                
                try:
                    body_content = b"".join(response_body)
                    if not body_content:
                         data = None
                    else:
                        data = json.loads(body_content)
                    
                    # Wrap it
                    wrapped_data = {
                        "code": 200,
                        "msg": "success",
                        "data": data
                    }
                    
                    # Re-create response with new content
                    new_body = json.dumps(wrapped_data, ensure_ascii=False).encode("utf-8")
                    response.headers["Content-Length"] = str(len(new_body))
                    
                    return Response(
                        content=new_body,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type="application/json"
                    )
                except Exception:
                    # If parsing fails or something else, return original
                    return response
        
        return response
