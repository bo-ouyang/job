from elasticsearch import AsyncElasticsearch
from config import settings
from core.logger import sys_logger as logger


class ESManager:
    def __init__(self):
        self.es: AsyncElasticsearch = None

    async def connect(self):
        """建立连接"""
        if self.es is None:
            es_url = settings.ES_URL
            logger.info(f"Connecting to Elasticsearch at {es_url}")
            # 如果需要认证: basic_auth=(settings.ES_USER, settings.ES_PASSWORD)
            auth = None
            if settings.ES_PASSWORD:
                auth = (settings.ES_USER, settings.ES_PASSWORD)
            self.es = AsyncElasticsearch(
                es_url,
                basic_auth=auth,
                verify_certs=False # 开发环境关闭证书校验
            )
            
    async def close(self):
        """关闭连接"""
        if self.es is not None:
            await self.es.close()
            self.es = None

    async def get_es(self) -> AsyncElasticsearch:
        if self.es is None:
            await self.connect()
        return self.es
        
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            es = await self.get_es()
            is_ping = await es.ping()
            if is_ping:
                 logger.info("Elasticsearch is connected and healthy.")
            return is_ping
        except Exception as e:
            logger.error(f"Elasticsearch connection failed: {e}")
            return False

es_manager = ESManager()

async def get_es() -> AsyncElasticsearch:
    return await es_manager.get_es()
