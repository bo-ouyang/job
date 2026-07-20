# 爬虫更新总结 (2026-02-07)

本文档总结了对爬虫组件所做的更改。

## 1. 同步逻辑 (`hasMore`)

改进了 GUI 控制器 (Playwright/Selenium) 与 Scrapy 爬虫之间的协调机制。

-   **Mitmproxy 插件 (`boss_mitm_addon.py`)**: 拦截 API 响应中的 `hasMore` 字段，并将其转发给 Scrapy Bridge。
-   **爬虫 (`boss_monitor_spider.py`)**: 
    -   接收 `hasMore` 状态。
    -   将此状态写入 `task_status.json`。
-   **GUI 控制器 (`boss_gui_controller.py`)**:
    -   持续检查 `task_status.json`。
    -   当 `has_more` 变为 `False` 时，**立即停止滚动**。
    -   仅当数据完全加载完毕后才循环到下一个任务。

## 2. 数据增强 (行业/城市)

修复了职位数据无法正确关联行业/城市上下文的问题。

-   **爬虫 (`boss_monitor_spider.py`)**:
    -   解析拦截到的 API URL 中的 `industry` 和 `city` 查询参数 (例如 `&industry=100021`)。
    -   基于这些 URL 参数设置 `item['industry_code']` 和 `item['city_code']`，覆盖或补充职位本身的详情数据。

## 3. 去重机制 (Redis + Bloom Filter)

使用高性能的 Redis Bloom Filter 替换了基础的数据库级去重。

-   **管道 (`jobCollection/pipelines/redis_dedup_pipeline.py`)**:
    -   使用 `mmh3` 哈希 (7 个哈希函数) 实现了自定义 **Bloom Filter**。
    -   使用 **Redis BitMap** (默认 32MB) 检查 `encrypt_job_id` 是否已存在。
    -   在数据到达数据库管道*之前*过滤重复项。
-   **配置 (`jobCollection/settings.py`)**:
    -   `BLOOM_BIT_SIZE_EXP`: 设置位图大小 (例如 25 = 2^25 bits ≈ 32MB)。
    -   `BLOOM_HASH_SEEDS`: 哈希函数的种子列表。
-   **爬虫 (`boss_monitor_spider.py`)**:
    -   更新了 `custom_settings`，以优先级 200 启用 `RedisDeduplicationPipeline`。

## 4. Scrapy 2.14+ 兼容性

修复了针对未来 Scrapy 版本的废弃警告。

-   **爬虫 (`boss_monitor_spider.py`)**:
    -   将 `start_requests(self)` 替换为 `async def start(self)`。
-   **管道 (`BossJobPipeline`, `RedisDeduplicationPipeline`)**:
    -   从 `process_item`、`open_spider` 和 `close_spider` 中移除了已废弃的 `spider` 参数。
    -   重构代码，通过 `from_crawler` 获取 `crawler` 实例访问 Spider (如有需要)。
