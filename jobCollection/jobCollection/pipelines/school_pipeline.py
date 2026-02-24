import asyncio
from collections import defaultdict
from scrapy.exceptions import DropItem
from sqlalchemy.dialects.mysql import insert

from common.databases.MysqlManager import db_manager
from common.databases.models.school import School
from common.databases.models.school_special import SchoolSpecial
from common.databases.models.school_special_intro import SchoolSpecialIntro

WRITE_ORDER = [School, SchoolSpecial, SchoolSpecialIntro]

class WriteBuffer:
    def __init__(self, max_rows=500, max_wait=1):
        self.queue = asyncio.Queue()
        self.buffer = defaultdict(list)
        self.max_rows = max_rows
        self.max_wait = max_wait

    async def push(self, model, row):
        await self.queue.put((model, row))

    async def run(self, writer_func):
        """单写协程"""
        while True:
            try:
                model, row = await asyncio.wait_for(self.queue.get(), timeout=self.max_wait)
                self.buffer[model].append(row)

                if self._size() >= self.max_rows:
                    await self.flush(writer_func)

            except asyncio.TimeoutError:
                if self.buffer:
                    await self.flush(writer_func)

    def _size(self):
        return sum(len(v) for v in self.buffer.values())

    async def flush(self, writer_func):
        batch = dict(self.buffer)
        self.buffer.clear()
        if batch:
           await writer_func(batch)

class SchoolPipeline:
    def __init__(self):
        self.buffer = WriteBuffer(max_rows=500, max_wait=1)

    async def open_spider(self, spider):
        await db_manager.initialize()
        self.writer_task = asyncio.create_task(self.buffer.run(self._db_write))

    async def close_spider(self, spider):
        await self.buffer.flush(self._db_write)
        self.writer_task.cancel()
        try:
             # Wait for writer task to be cancelled if needed
             pass
        except:
             pass
        spider.logger.info("Pipeline buffer flushed and task cancelled.")
        await db_manager.close()

    async def process_item(self, item, spider):
        # 优化：过滤无效ID
        if not item.get("id"):
             raise DropItem(f"Item {item.__class__.__name__} missing ID")

        model, data = self._item_to_model(item)
        await self.buffer.push(model, data)
        return item

    def _item_to_model(self, item):
        item_cls_name = item.__class__.__name__
        if item_cls_name == "SchoolItem":
            return School, dict(item)
        elif item_cls_name == "SchoolSpecialItem":
            return SchoolSpecial, dict(item)
        elif item_cls_name == "SpecialIntroItem":
            return SchoolSpecialIntro, dict(item)
        else:
            raise ValueError(f"Unknown item: {item_cls_name}")

    async def _db_write(self, batch):
        """🔥 整个系统唯一写入口"""
        async with (await db_manager.get_session()) as session:
            async with session.begin():   # 单事务
                for model in WRITE_ORDER:
                    if model not in batch:
                        continue
                    
                    data = batch[model]
                    if not data: continue

                    # 关键：锁顺序固定
                    try:
                        data.sort(key=lambda x: x.get("id", 0))
                    except:
                        pass # Should not happen if filtered

                    stmt = insert(model).values(data)
                    stmt = stmt.on_duplicate_key_update(
                        **{c.name: stmt.inserted[c.name]
                           for c in model.__table__.columns
                           if not c.primary_key}
                    )

                    await session.execute(stmt)
