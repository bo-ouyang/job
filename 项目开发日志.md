# 项目概览：招聘数据采集与智能分析平台

## 1. 简介

本项目是一个全栈架构的招聘数据采集与智能分析平台，主要针对 Boss 直聘进行职位与公司信息的定向爬取，通过大模型（LLM）对非结构化职位描述进行自动化特征重构与标签提炼，并提供 BI 级别的数据可视化与 AI 驱动的职业规划服务。

系统涵盖 C 端求职者应用（Vue 3 SPA）、后端 API 服务（FastAPI）、运营管理中台（Starlette-Admin）、智能爬虫调度集群（DrissionPage + Scrapy）以及完整的可观测性基础设施（Prometheus + Grafana）。

## 2. 架构与组件

该项目采用模块化微服务架构，包含五大核心组件：

### A. Web API (`jobCollectionWebApi`)

- **框架**: FastAPI (Python)，支持 uvicorn 多 Worker 生产部署。
- **用途**: 为前端 SPA 提供完整的 RESTful API（16 个 Controller，9 个 Service）。
- **核心特性**:
  - **数据库**: 异步 PostgreSQL 连接 (`PostgresManager`)，SQLAlchemy 2.0 + asyncpg。
  - **搜索引擎**: Elasticsearch 集成，支持全文搜索与聚合分析。
  - **AI 集成**: LangChain + DeepSeek/智谱 LLM，支持职业建议、罗盘报告、AI 语义搜索、简历解析。
  - **异步任务**: Celery 双队列（realtime / batch），AI 接口全异步化。
  - **弹性架构**: Circuit Breaker 熔断器、AI 结果级 Redis 缓存、分布式锁、`@cache` 装饰器。
  - **认证体系**: JWT 双 Token（Access 2h + Refresh 90d）+ 无感刷新 + 黑名单拦截。
  - **支付**: 支付宝 / 微信支付集成。
  - **可观测性**: Prometheus 自定义指标（12 项）+ FastAPI Instrumentator + 后台健康探针。
  - **日志**: Loguru 全链路接管（Uvicorn / Celery / App 分流按天落盘）。

### B. 前端 SPA (`frontend`)

- **框架**: Vue 3 + Vite
- **UI**: Element Plus + ECharts + echarts-wordcloud
- **核心页面**: 职位集市、职业罗盘、专业分析、BI 数据洞察、AI 简历生成、钱包充值等 15 个页面。
- **异步适配**: 通过 `pollTask.js` 通用轮询工具对接后端 Celery 异步 AI 端点。
- **认证**: Axios 双拦截器实现 401 静默刷新 + 请求队列缓冲。

### C. 智能爬虫调度 (`jobCollection`)

- **框架**: DrissionPage (Chromium 自动化) + Scrapy
- **列表爬虫** (`boss_list_drission_spider`): 浏览器驱动采集岗位列表，支持代理池 + Cookie 持久化。
- **详情爬虫** (`boss_detail_drission_spider`): Redis 流同步 + mitmproxy 拦截，串行获取 → 立即锁定 → 60s 超时保护。
- **批量解析** (`job_parser`): Celery 定时任务，Semaphore(3) 并发调用 LLM 提取结构化标签。
- **进程管控**: Admin 后台实时启停，支持 Play / Pause / Stop 一连串进程级操控。

### D. 运营调度中台 (`main_admin.py`)

- **框架**: Starlette-Admin (独立端口 8001)
- **功能**:
  - **RBAC 权限控制**: Admin / SuperAdmin / Operations 三级角色。
  - **数据看板**: 用户/职位/公司统计，实时服务器状态 (CPU/Mem/Disk)，数据库连接池监控。
  - **爬虫调度面板**: 创建/启动/暂停/停止 爬虫任务，实时状态同步。
  - **操作审计**: 自动记录管理员所有增删改操作 (`AdminLog`)。
  - **任务监控**: 通过 Celery Event 信号量拦截器展示任务健康数据与耗时。

### E. 可观测性 (`prometheus` + `grafana`)

- **Prometheus**: 每 15s 抓取 FastAPI `/metrics`，自动采集 HTTP RED 指标 + 12 项自定义业务指标。
- **Grafana**: 预置 12 面板看板（服务概览 / AI 监控 / 业务指标），Docker 启动零配置。

## 3. 技术栈

| 层级 | 技术 |
| ------ | ------ |
| **后端** | Python · FastAPI · uvicorn (多 Worker) |
| **前端** | Vue 3 · Vite · ECharts · Element Plus |
| **管控中台** | Starlette-Admin |
| **任务队列** | Celery (realtime / batch 双队列) · Redis |
| **数据库** | PostgreSQL (asyncpg + SQLAlchemy 2.0) |
| **搜索引擎** | Elasticsearch |
| **缓存/锁** | Redis (缓存 / 分布式锁 / Pub-Sub / WebSocket) |
| **AI/LLM** | LangChain Core · DeepSeek / 智谱 · Pydantic |
| **爬虫** | DrissionPage (Chromium) · Scrapy · mitmproxy |
| **弹性架构** | Circuit Breaker · `@cache` 装饰器 · TTL Jitter |
| **可观测性** | Prometheus · Grafana (预置看板) · Loguru |
| **支付** | 支付宝 / 微信支付 |
| **部署** | Docker Compose · uvicorn 多 Worker |

## 4. 项目现状

- **全栈就绪**: 前端 Vue 3 SPA + 后端 FastAPI + Admin 中台 + 爬虫集群全部具备生产部署能力。
- **AI 全异步化**: 3 大 AI 接口（职业建议/罗盘报告/AI 搜索）通过 Celery 异步处理 + 前端轮询完成闭环。
- **弹性基础设施**: 熔断器 + 多层缓存 + 队列隔离 + 多 Worker 部署，具备高并发防御能力。
- **可观测性**: Prometheus + Grafana 全景监控，覆盖 HTTP/AI/计费/基础设施四大维度。
- **数据模型**: 29 个 SQLAlchemy 模型，覆盖用户、岗位、简历、支付、爬虫任务、系统配置等完整业务域。

## 5. 最近更新 (2025-12-26)

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

## 6. 最近更新 (2026-01-03)

### Crawler Management Enhancement (爬虫管理增强)

- **Admin 功能完善**:
  - 修复了爬虫任务创建时的默认状态问题。
  - 新增了 **启动 (Run)**, **暂停 (Pause)**, **恢复 (Resume)**, **停止 (Stop)** 等任务管理操作。
- **爬虫架构优化**:
  - 将爬虫逻辑迁移至 `boss_monitor_spider.py`，并使其对接统一的 `BossCrawlTask` 数据模型。
  - 实现了爬虫进程与 Admin 操作的实时联动：
    - **启动**: 后台启动独立爬虫进程 (`scrapy crawl boss_monitor -a task_id=...`)。
    - **暂停/停止**: 爬虫在运行时会主动检测数据库状态变化，响应暂停等待或停止终止的指令。

## 7. 最近更新 (2026-01-09)

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

## 8. 最近更新 (2026-01-12 ~ 2026-01-22)

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

## 9. 最近更新 (2026-02-01)

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

## 10. 最近更新 (2026-02-04)

### 职业罗盘功能精细化与后端级联查询优化 (Career Compass & Materialized Path Optimization)

本次迭代大幅提升了“职业罗盘 (Career Compass)”的交互准确性与底层数据查询效率：

#### A. 行业级联搜索的 Materialized Path 改造

- **树形查询极致优化**：放弃了原先在 `get_rollup_codes` 与子节点下探查询中使用的**递归 CTE (Recursive CTE)**，为行业表 (`industries`) 引入了经典的 **Materialized Path (物化路径)** 字段 `path`。现在获取任意分类下的所有叶子节点仅需一次原生的 `LIKE '0/1000/%'` 极速前缀匹配，大幅度削减了分析大盘时的数据库耗时。
- **内存级别树组装**：重写了 `/industries/tree/` API，现在只进行**一次全量扫描查询**，随后在 Python 内存中使用字典 Hash-Map 将线性数据转化为多级树形结构，从 O(N^2) N+1 查询复杂度断崖式降至 O(N)。
- **安全拦截过滤**：修改了输出至前端的 `IndustryTree` Pydantic Schema，显式剔除了 `id` 和 `parent_id` 等底层数据库结构痕迹，保证对外网透出的 API 只存留 `code` 及其业务形态。

#### B. 罗盘大盘 (Career Compass) 联动改造

- **前端 CSS 布局扩容**：重构了 `CareerCompass.vue` 顶部的复合级联框样式，放宽了 `max-width` 限制并引入弹性边界，解决了级联菜单过长导致的元素挤压或同行断行问题。
- **全链路 Code 穿透**：重写了整个 AI 罗盘与词云 (Skill Cloud) 获取链路，将前置由 Vue 发出的 `行业名称 (String)` 强制替换为精确的 **级联行业 Code (Int)**。
- **两级下探精准画像**：修改了 `analysis_service.py` 中的 Elasticsearch 聚合统计逻辑，现在的 ES 请求支持同时接收并解析主行业与次级行业的 Code (例如 `industry` 和 `industry_2`)，使得生成的词云与 AI 职业规划报告极度贴合用户的最后一次精准鼠标落点。

## 11. 最近更新 (2026-02-15)

### 职业数据大盘深度修缮与缓存架构重构 (Dashboard Refinement & Cache Refactoring)

本次追加更新针对前端“职业罗盘”渲染生命周期、后端的缓存封装维度及基础 API 路由规范进行了系统级别的修缮与重塑。

#### A. Vue 渲染生命周期与 ECharts 挂载修复 (ECharts Lifecycle Fix)

- **DOM 挂载劫持修正**：修复了 `CareerCompass.vue` 界面中，当处于加载状态 (`v-loading`) 时 Vue 卸载宿主 DOM 节点，导致 ECharts 实例绑空 (`Initialize failed`) 的核心 Bug。
- **安全的 NextTick 释放**：重构了 `handleAnalyze` 函数的最终块 (`finally`)，利用 `nextTick` 确保 loading 状态彻底切断出队且真实 DOM 回归后才执行图表的 `initCharts` 与 `updateCharts`。同时增加了内置的实例清理机制 (`dispose()`)，彻底根除了前端页面的内存飙升泄漏问题。

#### B. API 路由基础规范回退修复 (API Routing Remediation)

- **405 动词冲突收敛**：根治了 `GET /api/v1/jobs` 抛出 `405 Method Not Allowed` 且被 307 重定向污染的问题。将 Controller 层中针对获取职位列表错误配置的 `@router.get("/jobs")` 修缮回基底 `@router.get("")`，打通了前端职位集市的数据血脉。

#### C. 服务端装饰器级的高阶缓存重构 (Decorator-driven Cache Architecture)

- **智能装饰器替换**：梳理界定了 `Service` 层“强防击穿缓存”与 `Controller` 层“防并发缓存”的边界界限。面向具备高频低负担的查询端点（如 获取行业树、获取级联类目），全面移除了繁冗的 Redis 编程式手搓代码。
- **切面注入**：以 `core.cache.py` 内部提供的泛型 `@cache` 装饰器一键接管了 Controller 层级的序列化 Hash 锁，精简了大量核心代码量的同时赋予了 API 本征态长效期与短期弹性的自控能力。保留底层核心 ES 查询的强阻断缓存锁机制，构成内外双层的完美缓存生态壁垒。

## 12. 最近更新 (2026-02-25)

### AI 服务弹性架构与全链路异步化改造 (AI Service Resilience & Full-Stack Async Transformation)

本次迭代实现了后台 AI 调用链的**全面弹性化改造**：从底层熔断器到上层接口异步化，覆盖后端基础设施、Celery 任务编排、前端轮询适配及生产部署四大维度。

#### A. Circuit Breaker 熔断器 (AI API Fault Isolation)

- **新增 `core/circuit_breaker.py`**：实现了完整的异步熔断器状态机，支持 `CLOSED → OPEN → HALF_OPEN` 三态流转。
  - **失败阈值**：连续 5 次 LLM 调用失败后自动熔断，60 秒冷却期后探测恢复。
  - **全覆盖集成**：将熔断器包裹至 `ai_service.py` 的全部 4 条 LLM 调用路径（`_call_llm_with_langchain`、`_call_llm`、`_call_llm_generic_text`、`_call_llm_generic`），杜绝 AI API 故障时的雪崩效应。
  - **用户友好降级**：熔断器 OPEN 状态下直接返回 `❌` 前缀的友善提示，而非让请求无限挂起。

#### B. AI 结果级 Redis 缓存 (Result-Level Caching)

- **`generate_career_advice`**：基于 `major + skills + engine` 的 MD5 摘要生成缓存键，命中后跳过 LLM 调用，缓存有效期 **24 小时**。
- **`get_career_navigation_report`**：基于 `major_name + es_stats` 的 Hash 摘要进行缓存，有效期 **12 小时**。
- **脏数据隔离**：仅缓存成功结果（不以 `❌` 开头的响应），错误响应不会被错误缓存。

#### C. Celery 队列分离与多 Worker 部署 (Queue Segmentation & Multi-Worker)

- **双队列路由**：修改 `celery_app.py`，引入 `realtime` 与 `batch` 双队列架构：
  - **Realtime 队列**：承载用户实时请求的 AI 任务（简历解析、职业建议、罗盘报告、AI 搜索）。
  - **Batch 队列**：承载后台定时批量任务（岗位解析 `job_parser`、ES 同步 `es_sync`、代理维护 `proxy_tasks`）。
- **独立 Worker 进程**：
  - `run_worker.bat` → 仅消费 `batch` 队列。
  - `run_worker_realtime.bat` (新增) → 仅消费 `realtime` 队列。
- **效果**：用户实时请求不再被后台数千条岗位批量解析任务阻塞，首次实现了用户体验与后台吞吐的物理隔离。

#### D. 批量 LLM 调用受控并发 (Batch Parsing Concurrency Control)

- **`job_parser.py` 改造**：将原先的串行逐条 LLM 解析重构为 `asyncio.Semaphore(3)` 控制的并发解析。
  - **预锁定**：批量将待处理岗位标记为 `ai_parsed=1`，防止多 Worker 重复领取。
  - **聚合执行**：`asyncio.gather` 并发调度，信号量限制最大 3 路同时调用，平衡吞吐与 API 限流。
  - **预期提升**：批量解析吞吐量提升约 **~3 倍**。

#### E. AI 接口全面异步化 (Full Async AI Endpoints via Celery)

- **新增 `tasks/ai_tasks.py`**：封装了 3 个 Celery 任务：
  - `career_advice_task`：职业建议生成。
  - `career_compass_task`：职业罗盘 AI 报告。
  - `ai_search_task`：AI 意图搜索 + ES 检索。
- **Controller 改造**：
  - `analysis_controller.py`：`POST /ai/advice` 与 `POST /career-compass` 改为提交 Celery 任务后立即返回 `{task_id, status: "pending"}`。
  - `job_controller.py`：`GET /ai_search` 同理改造，缓存命中时仍同步返回 `JobList`。
- **结果获取双通道**：
  - **轮询**：新增 `GET /analysis/ai/task/{task_id}` 和 `GET /jobs/ai_search/task/{task_id}`，前端定时拉取直至 `status === "completed"`。
  - **WebSocket 推送**：任务完成后通过 Redis Pub/Sub 向 WebSocket 频道推送，前端可实时接收（`career_advice_result`、`career_compass_result`、`ai_search_result`）。
- **计费策略**：权限校验和余额检查在 Controller 层同步完成（快速拦截），实际 AI 扣费在 Celery Worker 内使用独立 DB Session 延时执行。

#### F. uvicorn 多 Worker 生产部署 (Production Multi-Worker Deployment)

- **新增 `run_api_dev.bat`**：开发环境，单 Worker + 热重载（`uvicorn --reload`）。
- **新增 `run_api_prod.bat`**：生产环境，4 Worker 并行处理请求（`uvicorn --workers 4 --host 0.0.0.0`），大幅提升 HTTP 请求并发承载能力。

#### G. 前端异步适配 (Frontend Async Adaptation)

- **新增 `utils/pollTask.js`**：通用 Celery 任务轮询工具，封装超时控制、状态回调和错误处理。
- **`MajorAnalysis.vue`**：`fetchAIAdvice` 改为提交任务 → 轮询获取结果，新增缓冲态展示。
- **`CareerCompass.vue`**：`handleAnalyze` 中的 AI 报告环节改为异步轮询，缓存命中时秒级返回，未命中时优雅等待。
- **`JobMarket.vue`**：`executeAiSearch` 改为任务提交 → 轮询/缓存直返双通道。
- **向下兼容**：所有前端改造均保留了对旧版同步响应格式的兼容逻辑（`if (!taskId) ...`）。

## 13. 最近更新 (2026-03-1)

### 可观测性体系与架构文档化 (Observability Stack & Architecture Documentation)

本次追加更新引入了 **Prometheus + Grafana** 全链路监控与项目架构的系统性文档化。

#### A. Prometheus 可观测性集成 (Metrics Pipeline)

- **新增 `core/metrics.py`**：定义了 12 项自定义 Prometheus 指标，覆盖：
  - **Circuit Breaker**：熔断器状态 Gauge (`circuit_breaker_state`)、连续失败计数 (`circuit_breaker_failure_count`)、熔断触发总次数 Counter (`circuit_breaker_trips_total`)。
  - **AI / LLM**：调用总数 (`ai_llm_calls_total`)、调用耗时直方图 (`ai_llm_call_duration_seconds`)、缓存命中 (`ai_cache_hits_total`)。
  - **业务计费**：扣费次数 (`ai_billing_charges_total`)、拒绝次数 (`ai_billing_rejections_total`)。
  - **基础设施**：DB / ES 健康状态 (`infra_component_healthy`)，WebSocket 在线连接数 (`ws_connections_active`)。
- **FastAPI Instrumentator**：在 `main.py` 中集成 `prometheus-fastapi-instrumentator`，自动暴露 `/metrics` 端点，提供全路由的 HTTP RED 指标（Rate / Errors / Duration）。
- **后台健康探针**：新增 `_infra_health_probe_loop` 异步任务，每 15 秒探测 PostgreSQL / Elasticsearch / Circuit Breaker 状态并写入 Prometheus Gauge。
- **熔断器指标联动**：修改 `circuit_breaker.py`，在 CLOSED→OPEN 转换时自动递增 `circuit_breaker_trips_total` Counter。

#### B. Grafana 看板预置 (Zero-Config Dashboard)

- **自动化配置**：创建 `grafana/provisioning/` 目录，包含数据源 (`prometheus.yml`) 和看板加载器 (`default.yml`)，容器启动即自动注册 Prometheus 并加载预置看板。
- **预置看板 `job_platform_overview.json`**：共 12 个面板，分三大区域：
  - 🚦 **服务概览**：HTTP QPS + 5xx 速率、P50/P95/P99 延迟、DB/ES 健康状态灯。
  - 🤖 **AI 监控**：熔断器状态灯 (🟢/🟡/🔴)、失败仪表盘、熔断次数、缓存命中。
  - 📊 **业务指标**：Celery 任务提交趋势、热门 API TOP10、AI 计费扣款/拒绝。

#### C. Docker Compose 监控补全

- 新增 `prometheus` 服务（`:9090`，30 天数据留存）和 `grafana` 服务（`:3000`，默认 admin/admin）。
- 新增 `prometheus.yml` 抓取配置，每 15s 从 FastAPI `/metrics` 端点采集。

#### D. Elasticsearch 启动初始化

- 修改 `main.py` 的 `lifespan`，启动时自动调用 `es_manager.ensure_index()` 确保 ES 索引存在并应用最新 Mapping。
- 健康检查端点 `/health` 现已同时包含 DB 和 ES 的状态报告。

#### E. 项目架构文档化

- **新增 `ARCHITECTURE.md`**：涵盖系统全局架构（Mermaid 拓扑图）、技术栈矩阵、后端分层设计（16 Controller / 9 Service / 7 Core）、29 个数据模型 ER 图、数据采集流水线、前端 15 个页面模块清单、弹性高可用架构图、部署端口分配、JWT 认证与 AI 计费流程。

## 14. 最近更新 (2026-03-04)

### 核心 API 架构重构与网关安全层加固 (API Architecture Refactoring & Gateway Security)

本次核心迭代主要聚焦于 **API 容错规范化**、**全链路参数类型约束** 以及构建 **Web 应用网关立体防线**。

#### A. 全局业务异常与状态码规范化 (Global Exception & Error Code Standardization)

- **自定义异常基类体系**：抛弃裸露的 `HTTPException`，在 `core/exceptions.py` 定义了 `AppException` 及其派生子类（如 `UserNotFoundException`, `PermissionDeniedException`, `ExternalServiceException` 等）。
- **统一业务错误码**：在 `core/status_code.py` 中引入一套独立于 HTTP 状态码的业务级错误标号 (`StatusCode.BUSINESS_ERROR`, `StatusCode.AUTH_FAILED` 等)。
- **全局集中捕获**：经由 `main.py` 的 FastAPI 全局 Exception Handler 统一拦截 `AppException` 并将其规范为一致的 `{"code", "msg", "data"}` 响应报文返回。

#### B. 网关层安全防线加固 (Gateway Security Headers & WAF Middleware)

- **Helmet Headers (`SecurityHeadersMiddleware`)**：
  - 自动向所有 HTTP 响应附加反 XSS (`X-XSS-Protection`)、防止 MIME 嗅探 (`X-Content-Type-Options: nosniff`)、HSTS 强制 HTTPS (`Strict-Transport-Security`) 以及反点击劫持 (`X-Frame-Options: DENY`) 头。
  - **框架指纹隐身**：隐蔽真实的底层引擎标识 (移除 `server: uvicorn`)，统一伪装为 `OceanServer` 混淆探测。
- **自定义 WAF 门禁 (`WAFMiddleware`)**：
  - 实现一层轻量级 Query 探测防漏墙，利用正则提前在中间件层熔断诸如 `' OR 1=1` (SQL 注入) 或 `<script>` (跨站脚本) 特征的恶意载荷请求并封禁请求端点 (`403 Forbidden`)。

#### C. 数据抽象层解耦与深层校验 (Schema Layer Decoupling & Deep Validation)

- **全局 Schema 文件标准化更名**：应用一键重构脚本，将所有的 Pydantic 数据类文件（原 `job.py`, `user.py`等）全量变更为 `*_schema.py` 约定名风格，根除了内部模块名与 `crud` 文件夹及标准库的循环引入冲突。
- **类解耦与 Pydantic 原生验证器**：
  - 将庞杂的 `JobQueryParams` 依赖从 `dependencies.py` 中剥离并迁入专属的 Data Schema 层 (`job_schema.py`)，重构为纯正的 Pydantic `BaseModel`。
  - **多字段联动校验 (`@model_validator`)**：直接在 Schema 级内聚完成了诸如 `salary_min <= salary_max` 之类的深度逻辑验证。
- **参数收口防御**：为整个项目的各独立 Controller（支持搜索参数、行业、关键字查询等入口）全面追加了严苛的 `max_length` 防击穿约束与正则类型限制。

#### D. 限流器原子操作升级 (Atomic Redis Rate Limiting)

- **Lua 脚本原子锁执行**：彻底重写了 `RateLimiter`（存在于 `dependencies.py`），采用 Redis Lua 脚本原子性包装 `INCR` 和 `EXPIRE` 命令，根治了极端并发下限流器可能产生僵尸 Key（永不过期）和越权绕过限流机制的设计漏洞。

## 15. 最近更新 (2026-03-04 续)

### AI 任务全生命周期管理与通知中心 (AI Task Lifecycle Management & Notification Center)

本次大规模更新实现了 AI 长时任务的 **全链路管理闭环**：从后端并发控制、持久化、监控，到前端跨页面状态保持与实时通知，构建了完整的企业级 AI 任务管理体系。

#### A. AI Controller 抽取与并发锁 (Controller Extraction & Concurrency Lock)

- **新增 `ai_controller.py`**：将散落在 `analysis_controller.py` 和 `resume_controller.py` 中的 AI 端点统一抽取至独立 Controller，包含 5 个端点：
  - `POST /ai/advice` — AI 职业建议
  - `POST /ai/career-compass` — 职业罗盘分析
  - `POST /ai/parse-resume` — 简历智能解析
  - `GET /ai/task/{task_id}` — 任务轮询（Redis-first → PG → Celery 三级降级）
  - `GET /ai/tasks/history` — 历史记录分页
- **每用户每接口并发锁**：基于 `Redis SET NX EX` 原子操作，一个用户同一时间只能执行一个同类 AI 任务（AI 搜索除外），前后端同时拦截并返回 `409 + AI_TASK_RUNNING (40902)` 业务错误码。

#### B. AiTask 数据模型与 Redis-First CRUD

- **新增 `AiTask` SQLAlchemy 模型**：记录 `user_id`, `celery_task_id`, `feature_key`, `status`, `request_params` (JSONB), `result_data` (TEXT), `execution_time`, `error_message` 等完整生命周期字段，含 `(user_id, feature_key, status)` 复合索引。
- **Redis-First 查询模式 (`crud/ai_task.py`)**：
  - 活跃锁查询：Redis `GET` → PG fallback。
  - 结果查询：Redis 结果缓存 (TTL 1h) → PG fallback。
  - 全部 Redis 操作均有 `try/except` 降级，Redis 崩溃不影响核心功能。

#### C. Celery 任务回写与去重缓存 (Task Callbacks & Dedup Cache)

- **完成/失败回写**：`ai_tasks.py` 与 `resume_parser.py` 的 Celery 任务在执行结束后自动调用 `mark_completed` / `mark_failed`，同步更新 PG 状态 + 释放 Redis 锁 + 写入结果缓存。
- **生产级增强**：`acks_late=True` + `time_limit=300` + `soft_time_limit=270`，防止任务丢失与无限挂起。
- **请求去重缓存**：对请求参数做 MD5 摘要 → Redis `ai_task:dedup:{feature}:{hash}` (TTL 1h)。相同参数已有完成结果时直接返回缓存，避免重复提交浪费 LLM 调用。
- **僵死任务清理**：新增 `ai_task_cleanup.py` Celery Beat 定时任务，每 5 分钟扫描 `status=pending/processing` 且 `created_at > 10min` 的记录，检查 Celery result backend 恢复或标记失败并释放锁。

#### D. Prometheus 指标扩展 (AI Task Metrics)

- **新增 6 项指标** (`core/metrics.py`)：
  - `ai_task_created_total` / `ai_task_completed_total` / `ai_task_failed_total` — 按 feature 分类计数。
  - `ai_task_rejected_total` — 并发锁拒绝计数。
  - `ai_task_duration_seconds` — Histogram，桶范围 1s~300s。
  - `ai_task_dedup_hits_total` — 去重命中计数。
- **采集点**：Controller 层计 `created` / `rejected` / `dedup_hits`，Worker 层计 `completed` / `failed` / `duration`。

#### E. WebSocket 统一任务通知 (Unified Task Notification)

- **后端双层通知**：任务完成/失败时，Celery Worker 通过 Redis Pub/Sub 同时推送：
  - 功能级消息（`career_advice_result`, `resume_parsed` 等）— 向后兼容。
  - 统一消息（`ai_task_completed` / `ai_task_failed`）— 携带 `task_id`, `feature_key`, `status`, `message` 中文提示。
- **前端全局捕获**：`BasicLayout.vue` 的 WS `onmessage` 中捕获统一通知，调用 `ElNotification` 弹窗提示，同时写入 Pinia store。

#### F. 前端 AI 任务通知中心 (Frontend Notification Center)

- **新增 `stores/aiTask.js` (Pinia Store)**：全局管理所有 AI 任务状态与结果缓存，页面切换不丢失。
  - `addTask()` — 提交任务时注册。
  - `markCompleted()` / `markFailed()` — WS 消息自动更新。
  - `getLatestResult(featureKey)` — 读取上次完成结果（支持跨页面恢复）。
  - `pollAndUpdate()` — 替代原 `pollTaskResult`，轮询结果自动写入 store。
- **新增 `components/AiTaskPanel.vue`**：右侧滑出式抽屉面板，展示所有 AI 任务列表，包含状态图标（⏳🔄✅❌）、未读蓝点、进行中 spinner、耗时显示。
- **导航栏集成**：`BasicLayout.vue` 新增 🤖 图标入口，进行中任务显示黄色数量 badge，有未读结果显示蓝点。

#### G. 跨页面结果持久化 (Cross-Page Data Persistence)

- **`CareerCompass.vue`**：提交时 `aiTaskStore.addTask()`，轮询改用 `aiTaskStore.pollAndUpdate()`。`onMounted` 时调用 `getLatestResult('career_compass')` 恢复上次报告。
- **`MajorAnalysis.vue`**：同理，恢复 `career_advice` 上次结果。
- **效果**：用户提交 AI 任务后切换页面，再回到原页面，上次的结果仍然完整显示。

#### H. Grafana 仪表盘扩展

- **新增「🧠 AI 任务生命周期」行**，包含 6 个面板：
  - AI 任务创建/完成/失败速率 (timeseries)
  - AI 任务并发拒绝-锁冲突 (timeseries)
  - AI 任务去重命中 (stat)
  - AI 任务执行耗时 P50/P95 (timeseries)
  - AI 任务总量统计-累计 (stat，含四项指标)

## 16. 最近更新 (2026-03-06)

### 钱包、支付通知与数据库迁移治理

- 注册链路增强：`crud/user.py` 在普通注册与微信注册后自动创建钱包，初始余额默认 10。
- 充值通知补齐：`payment_controller.py` 在支付成功后新增站内消息写入，并尝试 WebSocket 实时推送给用户。
- 模型索引治理：为 `common/databases/models` 下全部模型补充 `__table_args__`，新增组合索引以优化常见查询路径。
- Alembic 正式接入：新增 `alembic.ini`、`alembic/env.py`、`alembic/script.py.mako` 与 `alembic/versions/` 目录。
- 首个迁移脚本：`alembic/versions/20260306_01_add_model_indexes.py`，用于落库本次新增索引（增量迁移）。
- 依赖更新：`requirements.txt` 与 `jobCollectionWebApi/requirements.txt` 新增 `alembic>=1.13.2`。
- 文档更新：`README.md` 新增「Database Migration (Alembic)」执行步骤与注意事项。

## 17. 最近更新 (2026-03-07)

### A. 首页统计与缓存修复

- 修复首页总量统计被 10000 截断问题：`analysis_service.py` 的 ES 聚合查询统一补充 `track_total_hits=true`。
- 新增总量解析兜底：兼容 `hits.total` 不同返回结构，统一取 `total_jobs`。
- 修复首页缓存未命中问题：重构 `core/cache.py`。
  - 缓存键改为 `signature.bind_partial(*args, **kwargs)` 后统一哈希，覆盖位置参数。
  - 命中判断从 truthy 改为 `cached_data is not None`。
  - 增加 cache hit/set 调试日志。
- 首页缓存键升级为 `analysis:home_stats_v4`，规避旧缓存污染。

### B. 查询性能优化

- 优化公司列表查询：
  - `company_controller.py` 由“分页查询 + 全表 count”改为“分页查询 + 同筛选条件 count”。
  - `crud/company.py` 增加 `_apply_filters` 与 `count_search`，并使用 `load_only` 减少字段加载。
  - 列表查询加入稳定排序，降低分页抖动。
- 优化通用 `CRUDBase.count`：从全量加载后 `len()` 改为数据库 `COUNT(*)`。

### C. 支付配置增强

- `payment_controller.py` 增加支付宝可选参数 `ALIPAY_APP_AUTH_TOKEN` 支持（ISV 模式可用）。
- 统一支付回调地址拼接逻辑，避免配置中手动带渠道后缀导致 `/alipay/alipay` 重复路径。
- `.env` / `.env.production` 补充与规范支付宝配置示例。

### D. 架构与文档更新

- 重写并更新 `README.md`，同步运行方式、迁移方式、支付配置关键项与近期变更。
- 升级 `ARCHITECTURE.md` 为结构化版本，补充：
  - 系统上下文与容器边界；
  - 首页统计 / AI 任务 / 支付三条关键时序；
  - 爬虫采集链路；
  - 数据库 ER 关系与查询约束。