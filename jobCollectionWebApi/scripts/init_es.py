import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.search.conn import get_es, es_manager
from schemas.es_mapping import JOB_INDEX_MAPPING
from config import settings
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_es_index():
    """初始化 ES 索引"""
    es = await get_es()
    index_name = settings.ES_INDEX_JOB
    
    try:
        # 1. 检查索引是否存在
        exists = await es.indices.exists(index=index_name)
        if exists:
            logger.info(f"Index '{index_name}' already exists. Deleting it to apply new mappings...")
            await es.indices.delete(index=index_name)
            
        # 2. 创建索引
        # 注意：如果 ES 没有安装 IK 分词器，这里可能会失败
        # 我们可以做一个降级处理，如果失败则尝试使用标准分词器
        try:
            await es.indices.create(index=index_name, body=JOB_INDEX_MAPPING)
            logger.info(f"Index '{index_name}' created successfully with mapping.")
        except Exception as e:
            logger.error(f"Failed to create index with IK analyzer: {e}")
            logger.info("Attempting fallback to standard analyzer...")
            
            # fallback: 移除 ik 相关配置
            fallback_mapping = JOB_INDEX_MAPPING.copy()
            del fallback_mapping["settings"]["analysis"]
            
            # 递归移除 properties 中的 analyzer
            def remove_analyzer(props):
                for k, v in props.items():
                    if "analyzer" in v:
                        del v["analyzer"]
                    if "search_analyzer" in v:
                        del v["search_analyzer"]
                    if "properties" in v:
                        remove_analyzer(v["properties"])
            
            remove_analyzer(fallback_mapping["mappings"]["properties"])
            
            await es.indices.create(index=index_name, body=fallback_mapping)
            logger.info(f"Index '{index_name}' created successfully with STANDARD analyzer.")
            
    except Exception as e:
        logger.error(f"Critical error initializing ES: {e}")
    finally:
        await es_manager.close()

if __name__ == "__main__":
    asyncio.run(init_es_index())
