import json
import time
from scrapy import signals
from common.databases.PostgresManager import db_manager
from common.databases.models.fetch_failure import FetchFailure


class FailureLoggerMiddleware:

    @classmethod
    def from_crawler(cls, crawler):
        inst = cls()
        crawler.signals.connect(inst.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(inst.spider_closed, signal=signals.spider_closed)
        return inst

    async def spider_opened(self, spider):
        await db_manager.initialize()
        spider.logger.info("FailureLoggerMiddleware DB ready")

    async def spider_closed(self, spider):
        await db_manager.close()

    async def process_exception(self, request, exception, spider):
        await self._save_failure(request, spider, error=str(exception), status=None)
        return None  # 交给 RetryMiddleware

    async def process_response(self, request, response, spider):
        if response.status >= 400:
            await self._save_failure(request, spider, error=f"HTTP {response.status}", status=response.status)
        return response

    async def _save_failure(self, request, spider, error, status):
        try:
            # 优化：安全的 JSON 序列化，防止 Request 对象等无法序列化的内容导致二次报错
            meta_str = json.dumps(dict(request.meta), ensure_ascii=False, default=str)[:65535]
            
            async with (await db_manager.get_session()) as session:
                failure = FetchFailure(
                    spider=spider.name,
                    url=request.url,
                    method=request.method,
                    status_code=status,
                    error=error[:65535],
                    meta=meta_str,
                    created_at=time.strftime("%Y-%m-%d %H:%M:%S")
                )
                session.add(failure)
                await session.commit()
        except Exception as e:
            spider.logger.error(f"写入失败表失败: {e}")
