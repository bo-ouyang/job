import copy

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
            auth = None
            if settings.ES_PASSWORD:
                auth = (settings.ES_USER, settings.ES_PASSWORD)
            self.es = AsyncElasticsearch(
                es_url,
                basic_auth=auth,
                #verify_certs=False  # 开发环境关闭证书校验
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

    async def ensure_index(self, index_name: str, mapping: dict, recreate: bool = False):
        """确保索引存在，不存在则创建；recreate=True 时先删除再重建"""
        es = await self.get_es()
        
        try:
            exists = await es.indices.exists(index=index_name)
            
            if exists and recreate:
                logger.info(f"Index '{index_name}' exists, recreating...")
                await es.indices.delete(index=index_name)
                exists = False
            
            if exists:
                logger.info(f"Index '{index_name}' already exists, skipping creation.")
                return
            
            # 尝试使用原始 mapping（含 IK 分词器）创建
            try:
                await es.indices.create(index=index_name, body=mapping)
                logger.info(f"Index '{index_name}' created successfully.")
            except Exception as e:
                logger.warning(f"Failed to create index with IK analyzer: {e}")
                logger.info("Falling back to standard analyzer...")
                
                # 降级：移除 IK 分词器相关配置
                fallback = copy.deepcopy(mapping)
                if "settings" in fallback and "analysis" in fallback["settings"]:
                    del fallback["settings"]["analysis"]
                
                def _remove_analyzer(props):
                    for v in props.values():
                        v.pop("analyzer", None)
                        v.pop("search_analyzer", None)
                        if "properties" in v:
                            _remove_analyzer(v["properties"])
                
                if "mappings" in fallback and "properties" in fallback["mappings"]:
                    _remove_analyzer(fallback["mappings"]["properties"])
                
                await es.indices.create(index=index_name, body=fallback)
                logger.info(f"Index '{index_name}' created with STANDARD analyzer (fallback).")
                
        except Exception as e:
            logger.error(f"Critical error ensuring index '{index_name}': {e}")
            raise

es_manager = ESManager()

async def get_es() -> AsyncElasticsearch:
    return await es_manager.get_es()
