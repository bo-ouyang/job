# 项目概览：招聘数据采集与分析平台

## 1. 简介

本项目是一个招聘数据采集与分析平台，旨在从招聘网站（目前主要针对 Boss 直聘）抓取职位信息，存储到数据库中，并提供 RESTful API 用于数据访问和潜在的分析功能。

## 2. 架构与组件

该项目采用模块化架构，主要包含三个核心组件：

### A. Web API (`jobCollectionWebApi`)

- **框架**: FastAPI (Python)
- **用途**: 为前端或其他服务提供 REST 接口。
- **核心特性**:
  - **数据库集成**: 异步 MySQL 连接 (`db.MysqlManager`)。
  - **路由**: API 版本控制 (`api.v1.api`)。
  - **模型校验**: 使用 Pydantic 模型进行请求/响应校验 (`schemas`)。
  - **依赖注入**: 支持依赖注入 (`dependencies.py`)。

### B. 爬虫 (`jobCollection`)
- **框架**: Scrapy 框架
- **用途**: 从外部源抓取职位数据。
- **核心组件**:
  - **Spiders**: `boss_job.py` (目前处于开发初期/半成品状态)。
  - **Pipelines**: `MySQLPipeline` 用于异步持久化数据到 MySQL。处理逻辑包括：
    - 检查职位是否已存在。
    - 保存公司和职位信息。
    - 分类并关联技能。
  - **Middleware**: 自定义中间件（可能用于代理或 Header 管理）。

### D. 后台管理系统 (`main_admin.py`)

- **框架**: Starlette-Admin (基于 FastAPI)
- **部署**: 独立服务部署在端口 8001，与主 API (8000) 分离。
- **功能**:
  - **RBAC 权限控制**: 支持 Admin, SuperAdmin, Operations (运营) 角色。运营角色仅拥有查看权限，无法删除数据。
  - **数据看板**: 首页 Dashboard 展示用户/职位/公司统计，以及实时的服务器状态 (CPU/Mem/Disk) 和数据库连接池监控。
  - **操作审计**: 自动记录管理员的所有增删改操作 (`AdminLog`)，支持审计查询。
  - **国际化**: 全面支持中文界面。

## 3. 技术栈

- **语言**: Python
- **Web 框架**: FastAPI
- **爬虫框架**: Scrapy
- **后台框架**: Starlette-Admin
- **数据库**:
  - **MySQL**: (已弃用) 代码保留但未激活。
  - **PostgreSQL**: 当前主要关系型数据库 (`common.databases.PostgresManager`)。
  - **Redis**: 用于分布式锁、缓存、Session 及 WebSocket 消息队列。
- **ORM**: SQLAlchemy (Async) with `asyncpg`
- **其他**:
  - `uvicorn`: ASGI 服务器。
  - `pydantic`: 数据校验。
  - `uvicorn`: ASGI 服务器。
  - `pydantic`: 数据校验。
  - `psutil`: 服务器性能监控。
  - **AI Integration**: Deepseek API 集成 (见 Config)。
  - **Payment**: 支付宝/微信支付集成框架。

## 4. 现状与观察

- **Scrapy 爬虫 (`boss_job.py`)** 尚处于早期或未完成阶段。
- **数据库模型** 结构良好，支持职位、公司、技能以及用户权限管理。
- **基础设施** 已完成 API 与 Admin 的微服务化拆分，提升了安全性和可维护性。

## 5. 最近更新 (2026-01-26)

本次迭代主要关注**简历智能化体验**、**后台监控增强**与**系统安全加固**：

### A. 智能简历创建 (Smart Resume)

- **直接上次生成**：在前端 (`MyResume.vue`) 实现了“上传 PDF 自动生成简历”的一键流程。
- **自动填充与保存**：后端 AI 解析完成后，前端会自动创建基础简历，并智能填充所有教育经历和工作经历，最后自动保存到数据库并刷新视图，真正实现了“无感生成”。

### B. 系统监控增强 (Celery Task Logging)

- **Celery 任务日志**：
  - 新增 `TaskLog` 模型 (`TaskLog` in `models/analysis` )。
  - 创建 `core/celery_events.py`，通过监听 `task_prerun`, `task_success`, `task_failure` 信号，自动记录所有后台任务的参数、执行状态、结果和耗时。
  - **可视化**：在后台管理系统 (`main_admin.py`) 中集成了“任务日志”视图，管理员可直接监控爬虫和解析任务的健康状况。

### C. 系统安全与体验优化

- **数据库修复**：修复了 SQLAlchemy 在 Async 模式下更新关联对象 (Resume Relations) 时的 `MissingGreenlet` 错误，确保了复杂对象更新的稳定性。
- **无感 Token 刷新 (Silent Refresh)**：
  - 前端 (`core/api.js`) 实现了 Axios 拦截器，当遇到 401 时自动暂停请求，使用 Refresh Token 换取新 Token 并重试，用户无感知。
  - **参数调整**：
    - Access Token 有效期延长至 **2小时**。
    - Refresh Token 有效期延长至 **90天**。
- **Admin 增强**：后台管理面板新增了 server 级别的监控信息。

## 6. 最近更新 (2026-02-13)

### Crawler Management Enhancement (爬虫管理增强)

- **Admin 功能完善**:
  - 修复了爬虫任务创建时的默认状态问题。
  - 新增了 **启动 (Run)**, **暂停 (Pause)**, **恢复 (Resume)**, **停止 (Stop)** 等任务管理操作。
- **爬虫架构优化**:
  - 将爬虫逻辑迁移至 `boss_monitor_spider.py`，并使其对接统一的 `BossCrawlTask` 数据模型。
  - 实现了爬虫进程与 Admin 操作的实时联动：
    - **启动**: 后台启动独立爬虫进程 (`scrapy crawl boss_monitor -a task_id=...`)。
    - **暂停/停止**: 爬虫在运行时会主动检测数据库状态变化，响应暂停等待或停止终止的指令。

## 7. 最近更新 (2026-02-13 补充)

### 详情页爬虫重构与同步优化 (Detail Spider Refactoring & Sync Optimization)

本次更新重点解决了 **数据采集重复**、**流程异常中断** 及 **并发冲突** 问题，建立了 Spider、Controller 与 Database 之间严格的串行同步机制。

#### A. 核心逻辑重构 (Core Logic Refactoring)
- **串行同步机制**: 
  - **Spider**: 获取任务 -> **立即标记 DB (Processing)** -> 推送 Redis -> 等待 `done` 信号。
  - **Controller**: 监听 Redis 队列 -> 浏览器导航 -> 轮询等待 Spider 处理完成 (`done`) 或超时。
  - **Mitmproxy**: 拦截响应数据 -> 推送至 Redis 供 Spider 消费。
- **防止重复采集**:
  - Spider 在获任务后 **立即** 更新数据库状态为 `is_crawl=2 (Processing)`，杜绝了因重启或并发导致的重复任务领取。
- **脏数据隔离**:
  - Spider 新增了 `current_job_id` 校验机制。若收到 Late Data（因超时而迟到的上一个任务响应），会记录警告并**忽略**，防止错误重置当前正在进行的任务状态。

#### B. 稳定性与健壮性 (Stability & Robustness)
- **URL 解析统一**: Spider 和 Controller 统一改用 `urllib.parse` 解析 Job ID，解决了 URL 参数（如 `?ka=...`）导致的 ID 不一致问题。
- **超时保护机制**:
  - **Spider**: 恢复了 60s 超时检查，自动重置死锁任务。
  - **Controller**: 增加了 15s 强制跳过机制，防止浏览器端死锁。
- **全链路汉化**: 将 Spider 和 Controller 的关键日志全部汉化，大幅降低了调试难度。

## 8. 最近更新 (2026-02-22 ~ 2026-02-23)

本次迭代主要集中在 **全局配置规范化**、**全链路日志重构** 以及 **爬虫自动控制调度** 的完善。

### A. 全局环境与配置集中化 (Configuration Centralization)
- 前期项目中存在多个文件硬编码敏感信息的问题（如 Redis/Elasticsearch 密码），现已将其全面抽离。
- 创建了统管全局环境的根目录 `.env` 并在 `.env.example` 中分发了样板。
- 适配了 `job_parser.py`、`boss_mitm_addon.py`、`boss_detail_gui_controller.py` 等各个边角脚本的环境拉取逻辑，保障各处都能顺畅连接中间件。

### B. 基于 Loguru 的现代化日志体系 (Loguru Globally Integrated)
- 废弃了散落各处的原生 Python `logging` 和 Uvicorn 默认干涩的请求日志，全盘切入 **Loguru**。
- `core/logger.py` 中实现了拦截器 (InterceptHandler)：
  - **Uvicorn 流量接管**：无缝剥离默认 Console 输出格式。
  - **全局异常透视**：`APILogMiddleware` 同样并入该流，并将原生抛出的异常通过 Loguru `diagnose=True` 的形态实现高可视度级别的堆栈变量回溯。
  - **Celery 调度台独立存档**：利用 Celery 信号 (`setup_logging`)，连同后台定时执行框架 Beat 的生命周期输出也全数纳入 Loguru 格式监控。
- **文件切割与留存**：按照主控制台应用 (`app_{date}.log`)、专向崩溃跟踪 (`error_{date}.log`) 与任务队列 (`celery_*.log`) 进行了分流，实现自动凌晨按天切分，各赋以 30 天 / 3 天的安全落盘留存期保护。

### C. WebAPI 全局异常阻断重写 (Exception Handling Refactor)
- 解决 FastAPI 原生拦截器中返回 `str(exc)` 导致异常报告扁平化的问题。
- 介入 `RequestValidationError` 并规范化：422 参数缺失/校验报错此时能下发完整的 Pydantic 错误对象列表，大大减轻排障负担。
- 新增 `SQLAlchemyError` 底仓异常熔断器：诸如并发操作时的 `IntegrityError`（如重复插入邮箱）等底仓级失败不再直接触发 500 崩溃，而是向上层规范回射 `409 Conflict` 友善提示。

### D. Admin 后台爬虫调度的桥接修正 (Admin Crawler IPC Pipeline)
- 修正了 `admin/views` 层启动爬虫命令时的名称遗漏，从 `boss_monitor` 修复回了能够被 Scrapy 真正响应的列表提取器 `boss_list`。
- **孤岛重连**：`boss_list_spider.py` 的底层状态轮询库已被纠正，从废弃的、不同步的 `SpiderBossCrawlUrl` 一举切换至当前 Admin 正在操作的主表 `BossCrawlTask`。
- 实现了 Web管理面板对正在疯狂爬取的 `scrapy` 进程的真实中断控制（当收到 `stopped` 信号抛出 `CloseSpider`）。
- **指令携参预埋**：重写了 `crawler_service.py` 的 `subprocess` 激发方法，强制追加接收和投递 `-a task_url=...` 变长参数，以为接下来的“单机构职位页直抓”埋下功能拓展的种子。

## 9. 最近更新 (2026-02-24)

### 核心基础设施弹性与前端 C 端联动闭环 (Core Infrastructure Resilience & C-Side Auth Loop)

本次迭代突破点在于**高并发防御机制**的落实、**认证链路体系**的接通，以及**数据聚类分析精准度**的修复。

#### A. Redis 缓存高可用改造 (Resilient Caching Strategy)
- **缓存穿透防护 (Penetration Protection)**：修改 `RedisManager.py`，允许对空结果（None/空列表）写入短期缓存，防范恶意查空穿透底层 DB。
- **缓存雪崩防护 (Avalanche Jittering)**：在核心缓存写入层引入了基于基础 TTL 额外浮动 10%~20% 的时间抖动机制（TTL Jitter），防止大批键在同一秒失效形成压力洪峰。
- **分布式并发锁 (Distributed Lock)**：创新实现了基于 `SETNX` 的异步锁上下文管理器 (`cache_lock`)。它被优先安置于高耗时的 Elasticsearch 分析聚合和 Postgres 兜底查询之前，杜绝热点 Key 瞬间失效时的缓存击穿 (Hot-Key Breakdown) 惨案。

#### B. JWT 认证与 C 端状态管理 (Robust JWT & State Control)
- **拦截器黑名单 (Blacklist Guard)**：在后端的 FastAPI Dependency 层 (`get_current_user`)，全面挂载并激活了 `is_token_blacklisted` 拦截。保障登出 (Logout) 和扫码冲突等情况下的废弃令牌能实现毫秒级的失效。
- **自动化无感刷新 (Silent Rotation in Vue)**：探明并跑通了独立封装在 Vue 侧 `core/api.js` 中的高阶 Axios 双拦截器。面临 401 拒收时，前端队列缓冲请求并静默投递 Refresh Token 换签重试。
- **Favorites 功能与 UI 连通**：完全激活了 C 端用户的职务收藏流程。成功在 `JobMarket.vue` 实现带权限管控的 `❤️ 收藏` 按钮，并完成了后端 `/api/v1/favorites/jobs` 数据链路的接驳验证，完善了用户体验。

#### C. 数据映射与 AI 端点修复 (Mapping Calibration)
- 修正了 ES 同步脚本 (`es_sync_all.py` / `es_sync.py`) 的抽取规则：支持完整的 `city_code` 和 `industry_code` 整型建树并同步至 Elasticsearch。
- 修复了 `analysis_service.py` 层级连投递 ID 参数（如 `industry`, `location`）导致的查询报错。消除了强制拦截抛出的 `ValueError`，在 ES 查询 DSL 构建时：若传 `location`，则直接匹配 `city_code`；若传 `industry` 大类，则利用映射的 PostgreSQL 关系回溯补查全系子行业 Code 并带入 ES 的 `terms` (In 查询) 中完美解决数据穿透过滤。
