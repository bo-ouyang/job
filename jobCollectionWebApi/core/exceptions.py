from typing import Any, Optional
from core.status_code import StatusCode

class AppException(Exception):
    """
    业务逻辑异常基类
    
    所有在 API 服务和 Service 层中主动抛出的业务失败，
    都应继承或直接实例化此类及其子类，从而可以通过统一的拦截器格式化输出给前端。
    """
    def __init__(
        self, 
        message: str = "系统业务异常", 
        code: int = StatusCode.BUSINESS_ERROR, 
        status_code: int = 400,
        data: Optional[Any] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code # 返回的 HTTP 状态码
        self.data = data
        super().__init__(self.message)

class AuthFailedException(AppException):
    """认证失败/Token失效异常"""
    def __init__(self, message: str = "认证失败，请重新登录", data: Optional[Any] = None):
        super().__init__(message=message, code=StatusCode.AUTH_FAILED, status_code=401, data=data)

class PermissionDeniedException(AppException):
    """无权限异常"""
    def __init__(self, message: str = "权限不足，拒绝访问", data: Optional[Any] = None):
        super().__init__(message=message, code=StatusCode.PERMISSION_DENIED, status_code=403, data=data)

class UserNotFoundException(AppException):
    """用户不存在"""
    def __init__(self, message: str = "用户不存在", data: Optional[Any] = None):
        super().__init__(message=message, code=StatusCode.USER_NOT_FOUND, status_code=404, data=data)

class UserDisabledException(AppException):
    """用户被禁用"""
    def __init__(self, message: str = "该账号已被冻结或禁用", data: Optional[Any] = None):
        super().__init__(message=message, code=StatusCode.USER_DISABLED, status_code=403, data=data)

class ExternalServiceException(AppException):
    """调用第三方服务失败 (大模型/微信/短信等)"""
    def __init__(self, message: str = "调用外部依赖服务失败", data: Optional[Any] = None):
        super().__init__(message=message, code=StatusCode.EXTERNAL_SERVICE_ERROR, status_code=500, data=data)
