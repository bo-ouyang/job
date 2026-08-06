# 重复代码报告

## 应删除的架构级重复

1. GUI/Mitm/Redis 旧捕获架构
   - `boss_base_spider.py:56-238`
   - `boss_list_spider.py:35-202`
   - `boss_detail_spider.py:27-159`
   - `boss_mitm_addon.py:39-142`
   - `boss_list_gui_controller.py:29-215`
   - `boss_detail_gui_controller*.py`
   - 原因：Drission Spider 已直接控制浏览器和读取响应；旧链路路径失效、任务表分叉、无法完成 Stage 1。

2. 点击详情实验
   - 列表解析复制：`boss_detail_click_drission_spider.py:254-306,468-592`
   - 浏览器/登录复制：`boss_detail_click_drission_spider.py:598-823`
   - 状态断点：`boss_detail_click_drission_spider.py:893-909`
   - 原因：无启动入口，producer/consumer 状态不匹配，功能已由列表与独立详情 Spider 覆盖。

3. 学校 MySQL Spider
   - `school.py:9-136`
   - `school_pipeline.py:13-109`
   - 原因：只存在手工 CLI 入口，依赖已废弃配置且不能加载；不应为废弃 Pipeline 再造共享 buffer。

## 应合并的现役重复

1. BOSS 列表 payload 和 Item 映射
   - 现役：`boss_list_drission_spider.py:319-443`
   - 实验：`boss_detail_click_drission_spider.py:468-592`
   - 旧版：`boss_list_spider.py:63-110`
   - 方案：一个纯解析/映射模块，Spider 只负责获取 payload。

2. 详情描述解析与落库
   - 解析：`boss_detail_drission_spider.py:368-378`、`boss_detail_spider.py:50-62`、`boss_detail_click_drission_spider.py:367-379`
   - 落库：`boss_pipeline.py:121-180`、`boss_detail_drission_spider.py:424-440`、`boss_detail_click_drission_spider.py:413-453`
   - 方案：保留一个解析器；详情一律产出 `BossJobDetailItem`，由 Pipeline 唯一写库并派发 ES。

3. 代理扩展、Cookie 和账户文件
   - 扩展：`boss_list_drission_spider.py:872-907`、`boss_detail_drission_spider.py:496-547`
   - Cookie：`boss_list_drission_spider.py:658-698`、`boss_detail_drission_spider.py:448-490`
   - 方案：小型文件工具函数；保留列表登录与匿名详情的合理特化。

4. 后台任务状态/进程终止
   - `crawler_service.py:79-139`
   - 方案：`reset_tasks()` 委托通用状态更新，不增加 registry/factory。

## 不应强行统一

- 列表登录浏览器与匿名详情浏览器的信任模型。
- Scrapy/浏览器/mitm 不同层级的代理适配；删除旧层级即可。
- PostgreSQL BOSS 写入与 MySQL 学校写入；学校路径应删除而不是泛化 repository。

