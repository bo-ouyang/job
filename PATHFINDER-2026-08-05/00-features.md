# jobCollection 功能清单

## 1. 后台现役 BOSS 列表采集

- 入口：`jobCollectionWebApi/admin/views/crawler.py:113-125`
- 调度：`jobCollectionWebApi/services/crawler_service.py:142-193`
- Spider：`jobCollection/jobCollection/spiders/boss_list_drission_spider.py:31-907`
- 入库：`jobCollection/jobCollection/pipelines/boss_pipeline.py:21-310`
- 状态：唯一明确接入运营后台的现役采集链路。

## 2. BOSS 岗位详情补全

- 入口：`jobCollection/jobCollection/spiders/boss_detail_drission_spider.py:26-40`
- 任务来源：`jobCollection/jobCollection/spiders/boss_detail_drission_spider.py:384-406`
- 状态：代码可独立运行，但没有后台调度；`major_name` 过滤使它无法消费现役列表产生的大多数 Job。

## 3. 专业/热门城市点击详情实验

- URL 生成：`jobCollection/jobCollection/simple_script/generate_boss_stu_urls.py:72-143`
- Spider：`jobCollection/jobCollection/spiders/boss_detail_click_drission_spider.py:31-50`
- 状态：生产者写 `pending`，消费者只读 `processing`，仓内没有调度入口。

## 4. 高考学校目录采集

- 入口：`jobCollection/jobCollection/spiders/school.py:9-23`
- Pipeline：`jobCollection/jobCollection/pipelines/school_pipeline.py:46-109`
- 状态：仅有 Scrapy CLI 入口；依赖已废弃且缺失配置的 MySQL，当前不能加载。

## 5. Legacy GUI/Mitm/Redis 桥接

- 编排：`jobCollection/run_pipeline.py:41-139`
- 基类：`jobCollection/jobCollection/spiders/boss_base_spider.py:12-238`
- 状态：旧任务表、GUI、mitmproxy、Redis 桥接与现役 Drission 直连架构并存；Stage 1 常驻不退出，无法自然进入详情阶段。

## 保留的共享边界

- PostgreSQL：`common/databases/PostgresManager.py:8-85`
- BOSS Item：`jobCollection/jobCollection/items/boss_job_item.py:3-49`
- BOSS Pipeline：`jobCollection/jobCollection/pipelines/boss_pipeline.py:21-310`
- 短信登录：`jobCollection/jobCollection/spiders/boss_sms_login_handler.py:31-1107`

