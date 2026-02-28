import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.search.conn import es_manager
from schemas.es_mapping import JOB_INDEX_MAPPING
from config import settings
from core.logger import sys_logger as logger


async def init_es_index():
    """初始化 ES 索引（删除并重建）"""
    try:
        await es_manager.ensure_index(
            index_name=settings.ES_INDEX_JOB,
            mapping=JOB_INDEX_MAPPING,
            recreate=True
        )
    except Exception as e:
        logger.error(f"Critical error initializing ES: {e}")
    finally:
        await es_manager.close()

if __name__ == "__main__":
    asyncio.run(init_es_index())
