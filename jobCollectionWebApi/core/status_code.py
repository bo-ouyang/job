from enum import IntEnum

class StatusCode(IntEnum):
    """API 响应状态码"""
    SUCCESS = 200
    
    # 客户端错误
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    TOO_MANY_REQUESTS = 429
    
    # 服务端错误
    INTERNAL_SERVER_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

    # 业务侧自定义错误码 (5 digits)
    # 通用业务错误
    BUSINESS_ERROR = 40000
    PARAMS_ERROR = 40001
    
    # 认证与授权 (401xx, 403xx)
    TOKEN_EXPIRED = 40101
    AUTH_FAILED = 40102
    PERMISSION_DENIED = 40301
    
    # 用户相关 (404xx, 409xx)
    USER_NOT_FOUND = 40401
    USER_ALREADY_EXISTS = 40901
    USER_DISABLED = 40302
    
    # AI 任务相关 (409xx)
    AI_TASK_RUNNING = 40902       # 同一功能已有任务在执行中

    # 爬虫/第三方调用错误 (500xx)
    EXTERNAL_SERVICE_ERROR = 50001
    SPIDER_TASK_ERROR = 50002
