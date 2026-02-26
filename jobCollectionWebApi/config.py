import os
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
current_dir = os.path.dirname(os.path.abspath(__file__))  # Job/jobCollectionWebApi/
project_root = os.path.dirname(current_dir) # Job/
env_path = os.path.join(project_root, ".env")  # Job/.env
load_dotenv(dotenv_path=env_path, override=True)  # override=True：覆盖系统环境变量

class Settings(BaseSettings):
    """应用配置"""
    # def __init__(self, **kwargs):
    #     #super().__init__(**kwargs)
    #     # 解析 API Keys
    #     api_keys = os.getenv('API_KEYS', '')
    #     if api_keys:
    #         self.API_KEYS = [key.strip() for key in api_keys.split(',')]
    # API 配置
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "求职技能分析平台"
    
    # CORS 配置
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000", 
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081", 
        "http://127.0.0.1:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8082"
    ]
    
    
    
    # 微信登录配置
    WECHAT_APP_ID: str = os.getenv('WECHAT_APP_ID', '')
    WECHAT_APP_SECRET: str = os.getenv('WECHAT_APP_SECRET', '')
    WECHAT_REDIRECT_URI: str = os.getenv('WECHAT_REDIRECT_URI', '')
    
    # 短信服务配置
    SMS_ACCESS_KEY_ID: str = os.getenv('SMS_ACCESS_KEY_ID', '')
    SMS_ACCESS_KEY_SECRET: str = os.getenv('SMS_ACCESS_KEY_SECRET', '')
    SMS_SIGN_NAME: str = os.getenv('SMS_SIGN_NAME', '')
    SMS_TEMPLATE_CODE: str = os.getenv('SMS_TEMPLATE_CODE', '')
    
    # Redis 配置
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB: int = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD: str = os.getenv('REDIS_PASSWORD', '')
    REDIS_KEY_PREFIX: str = os.getenv('REDIS_KEY_PREFIX', '')
    REDIS_MAX_CONNECTIONS: int = int(os.getenv('REDIS_MAX_CONNECTIONS', 100))
    REDIS_SOCKET_TIMEOUT: int = int(os.getenv('REDIS_SOCKET_TIMEOUT', 5))
    REDIS_SOCKET_CONNECT_TIMEOUT: int = int(os.getenv('REDIS_SOCKET_CONNECT_TIMEOUT', 5))
    REDIS_RETRY_ON_TIMEOUT: bool = os.getenv('REDIS_RETRY_ON_TIMEOUT', 'true').lower() == 'true'
    REDIS_CACHE_EXPIRE: int = int(os.getenv('REDIS_CACHE_EXPIRE', 1800))
    REDIS_SESSION_EXPIRE: int = int(os.getenv('REDIS_SESSION_EXPIRE', 1800))
    REDIS_JOB_EXPIRE: int = int(os.getenv('REDIS_JOB_EXPIRE', 86400))
    REDIS_JOB_EXPIRE: int = int(os.getenv('REDIS_JOB_EXPIRE', 86400))
    REDIS_ANALYSIS_EXPIRE: int = int(os.getenv('REDIS_ANALYSIS_EXPIRE', 7200))

    # Elasticsearch 配置
    ES_HOST: str = os.getenv('ES_HOST', 'localhost')
    ES_PORT: int = int(os.getenv('ES_PORT', 9200))
    ES_USER: str = os.getenv('ES_USER', 'elastic')
    ES_PASSWORD: str = os.getenv('ES_PASSWORD', '')
    ES_INDEX_JOB: str = os.getenv('ES_INDEX_JOB', 'jobs')
    ES_SCHEME: str = os.getenv('ES_SCHEME', 'https') # ES 8.x 默认 https
    
    @property
    def ES_URL(self) -> str:
        """生成 ES 连接 URL"""
        return f"{self.ES_SCHEME}://{self.ES_HOST}:{self.ES_PORT}"
    
    # MySQL 配置 (Deprecated)
    # MYSQL_HOST: str = os.getenv('MYSQL_HOST', 'localhost')
    # MYSQL_PORT: int = int(os.getenv('MYSQL_PORT', 3306))
    # MYSQL_USER: str = os.getenv('MYSQL_USER', 'root')
    # MYSQL_PASSWORD: str = os.getenv('MYSQL_PASSWORD', 'GODFATHER0220')
    # MYSQL_DATABASE: str = os.getenv('MYSQL_DATABASE', 'job')
    # MYSQL_CHARSET: str = os.getenv('MYSQL_CHARSET', 'utf8mb4')
    
    # # MySQL 连接池配置
    # MYSQL_POOL_MIN_SIZE: int = int(os.getenv('MYSQL_POOL_MIN_SIZE', 5))
    # MYSQL_POOL_MAX_SIZE: int = int(os.getenv('MYSQL_POOL_MAX_SIZE', 50))
    # MYSQL_POOL_RECYCLE: int = int(os.getenv('MYSQL_POOL_RECYCLE', 3600))
    # MYSQL_POOL_PRE_PING: bool = os.getenv('MYSQL_POOL_PRE_PING', 'true').lower() == 'true'
    # MYSQL_POOL_ECHO: bool = os.getenv('MYSQL_POOL_ECHO', 'false').lower() == 'true'
    
    # # MySQL 超时配置
    # MYSQL_CONNECT_TIMEOUT: int = int(os.getenv('MYSQL_CONNECT_TIMEOUT', 10))
    # MYSQL_READ_TIMEOUT: int = int(os.getenv('MYSQL_READ_TIMEOUT', 30))
    # MYSQL_WRITE_TIMEOUT: int = int(os.getenv('MYSQL_WRITE_TIMEOUT', 30))
    
    # # 其他 MySQL 配置
    # MYSQL_AUTOCOMMIT: bool = os.getenv('MYSQL_AUTOCOMMIT', 'true').lower() == 'true'
    # MYSQL_AUTOFLUSH: bool = os.getenv('MYSQL_AUTOFLUSH', 'true').lower() == 'true'
    # # Other MySQL Config...
    # MYSQL_EXPIRE_ON_COMMIT: bool = os.getenv('MYSQL_EXPIRE_ON_COMMIT', 'true').lower() == 'true'

    # PostgreSQL 配置
    POSTGRES_HOST: str = os.getenv('POSTGRES_HOST', 'localhost') # Docker service name
    POSTGRES_PORT: int = int(os.getenv('POSTGRES_PORT', 5432))
    POSTGRES_USER: str = os.getenv('POSTGRES_USER', 'postgres')
    POSTGRES_PASSWORD: str = os.getenv('POSTGRES_PASSWORD', '')
    POSTGRES_DB: str = os.getenv('POSTGRES_DB', 'job')
    
    # PostgreSQL 连接池配置
    POSTGRES_POOL_MIN_SIZE: int = int(os.getenv('POSTGRES_POOL_MIN_SIZE', 5))
    POSTGRES_POOL_MAX_SIZE: int = int(os.getenv('POSTGRES_POOL_MAX_SIZE', 50))
    
    @property
    def DATABASE_URL(self) -> str:
        """生成 PostgreSQL 异步连接 URL"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
        
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """生成 PostgreSQL 同步连接 URL"""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Celery 配置
    # Celery 配置
    CELERY_BROKER_URL: str = os.getenv('CELERY_BROKER_URL', '')
    CELERY_RESULT_BACKEND: str = os.getenv('CELERY_RESULT_BACKEND', '')

    @field_validator('CELERY_BROKER_URL', mode='before')
    @classmethod
    def assemble_celery_broker_url(cls, v: str, info: Field) -> str:
        if v: return v
        # Fallback to building from Redis settings
        # Note: In Pydantic v2 validators, accessing other fields is tricky in class method 'before'
        # But we can rely on defaults or environment variables again if needed, 
        # OR better: use verify in @model_validator(mode='after')
        return "" 

    @model_validator(mode='after')
    def set_celery_urls(self):
        # Build URL if not set
        if not self.CELERY_BROKER_URL:
            auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
            self.CELERY_BROKER_URL = f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/2"
        
        if not self.CELERY_RESULT_BACKEND:
            auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
            self.CELERY_RESULT_BACKEND = f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/2"
        return self
    
    # 应用配置
    DEBUG: bool = os.getenv('DEBUG', 'false').lower() == 'true'
    ENVIRONMENT: str = os.getenv('ENVIRONMENT', 'development')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    
    # API 认证配置
    API_KEYS_STR: str = Field(default="", alias="API_KEYS")
    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    ALGORITHM: str = os.getenv('ALGORITHM', 'HS256')
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 120)) # 2 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', 90)) # 90 days
    @property
    def API_KEYS(self) -> List[str]:
        """将 API_KEYS_STR 转换为列表"""
        if not self.API_KEYS_STR:
            return []
        return [key.strip() for key in self.API_KEYS_STR.split(',') if key.strip()]
    # 速率限制配置
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(os.getenv('RATE_LIMIT_REQUESTS_PER_MINUTE', 60))
    
    
    
    @property
    def REDIS_URL(self) -> str:
        """生成 Redis 连接 URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        else:
            return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    # @property
    # def MYSQL_URL(self) -> str:
    #     """生成 MySQL 连接 URL"""
    #     return (
    #         f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
    #         f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
    #         f"?charset={self.MYSQL_CHARSET}"
    #     )
        
    # @property
    # def MYSQL_URL_SYNC(self) -> str:
    #     """生成 MySQL 连接 URL"""
    #     return (
    #         f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
    #         f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
    #         f"?charset={self.MYSQL_CHARSET}"
    #     )
    
    # AI 配置
    AI_ENABLED: bool = True
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "deepseek") # mock, openai
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_BASE_URL: str = os.getenv("AI_BASE_URL", "https://api.deepseek.com")
    AI_MODEL: str = os.getenv("AI_MODEL", "deepseek-chat")

    # 支付配置
    PAYMENT_NOTIFY_BASE_URL: str = os.getenv("PAYMENT_NOTIFY_BASE_URL", "http://localhost:8000/api/v1/payment/notify")
    
    # 支付宝配置
    ALIPAY_APP_ID: str = os.getenv("ALIPAY_APP_ID", "")
    ALIPAY_PRIVATE_KEY_PATH: str = os.getenv("ALIPAY_PRIVATE_KEY_PATH", "")
    ALIPAY_PUBLIC_KEY_PATH: str = os.getenv("ALIPAY_PUBLIC_KEY_PATH", "")
    ALIPAY_DEBUG: bool = os.getenv("ALIPAY_DEBUG", "true").lower() == "true"
    
    # 微信支付配置
    WECHAT_APP_ID: str = os.getenv("WECHAT_APP_ID", "") # 关联的 APPID
    WECHAT_MCH_ID: str = os.getenv("WECHAT_MCH_ID", "") # 商户号
    WECHAT_PRIVATE_KEY_PATH: str = os.getenv("WECHAT_PRIVATE_KEY_PATH", "") # 商户私钥路径
    WECHAT_CERT_SERIAL_NO: str = os.getenv("WECHAT_CERT_SERIAL_NO", "") # 证书序列号
    WECHAT_API_V3_KEY: str = os.getenv("WECHAT_API_V3_KEY", "") # APIv3 密钥
    
    # 文件上传配置
    UPLOAD_DIR: str = os.getenv('UPLOAD_DIR', os.path.join(project_root, 'static', 'uploads'))
    STATIC_URL_PREFIX: str = os.getenv('STATIC_URL_PREFIX', '/static')
    MAX_UPLOAD_SIZE: int = int(os.getenv('MAX_UPLOAD_SIZE', 10 * 1024 * 1024)) # 10MB
    ALLOWED_EXTENSIONS: List[str] = ['jpg', 'jpeg', 'png', 'gif', 'pdf', 'doc', 'docx']
    
    class Config:
        case_sensitive = True

settings = Settings()
