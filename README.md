# 招聘数据采集与智能分析平台

## 🚀 Job Collection And Analysis Platform

> 一个全栈架构的智能招聘数据采集、解析与后台管理平台

---

## 📌 项目简介

本项目旨在打造一个高效的外部岗职位数据采集平台。主要针对主流招聘平台进行职位及公司信息的定向爬取，并通过大模型（LLM）对爬取到的**非结构化职位描述及简历进行自动化的特征重构与标签提炼**。

结合了先进的异步微服务架构设计，系统具备一套独立的权限后台管理体系、完整的可视化任务追踪以及可靠的反爬/死锁恢复机制。

## 🏗️ 核心架构

项目采用模块化拆分架构，主要分为三大领域：

1. **🚀 Web API (`jobCollectionWebApi`)**
   - 基于 **FastAPI** 的高性能异步核心引擎，支持 **uvicorn 多 Worker 生产部署**。
   - 提供完备的 RESTful API，用于内部数据流转及前端大盘展示。
   - 依赖 **PostgreSQL** 进行核心元数据层级化存储。
   - 原生支持 **Loguru** 全链路可视化日志与 **全局 AppException 业务异常拦截体系**。
   - 搭载了 **独立 WAF 防火墙中间件** 与防 XSS/SQL 注入的**安全防护头 (Helmet Headers)**。
   - 集成 **Circuit Breaker 熔断器** 与 **Redis Lua 原子态限流器**，防止高并发雪崩与恶意盗刷。
   - **AI 任务全生命周期管理**：独立 `ai_controller` + `AiTask` 持久化模型 + Redis-First 并发锁 + 去重缓存 + 僵死清理 + Prometheus 18 项自定义指标。

2. **🕷️ 智能爬虫调度 (`jobCollection`)**
   - 基于 **Scrapy** 的专业采集器，搭配自定义 Middleware 规避封控。
   - **串行同步机制**：蜘蛛节点与 Controller 形成严密的 Redis 流同步（支持获取任务、加锁、采集完结与释放的生命周期管控）。
   - 实现"无惧重启"的工作流：利用数据库锁定、60s超时强制回收、15s跳过机制解决爬虫并发和孤儿进程痛点。

3. **🛡️ 运营调度中台  (`main_admin.py`)**
   - **Starlette-Admin** 构建的高频数据透视平台。
   - 集成爬虫调度的**实时操控界面**（提供 `Play`, `Pause`, `Stop` 一连串进程级通信管控）。
   - **自动化任务监控**：通过 Celery Event 信号量拦截器，平台管理员可直接监控定时轮询大模型解析以及底层 Celery Beatz 运行的每一次健康数据与耗时。
   - 支持多层级的 RBAC (Admin/SuperAdmin/Operations) 行为审计。

## ✨ 特色功能体验

- **🤖 大模型深度整合 (LangChain / 原生 OpenAI 协议)**：爬取入库的岗位，会交由 Celery 集群自动提交至 DeepSeek / 智谱 等模型进行异步剖析，提取结构化标签（福利待遇、技能树图谱）。
- **📄 AI 一键智能简历生成**：允许求职者上传 PDF 后，后端自动剥析建立关系数据库画像，前端无感回填成结构化履历。
- **🔄 全链路日志审计**：从 Web 请求 -> DB 事务 -> Celery 定时任务 -> Spider 子进程，全部集中经由 Loguru 分发按天落盘留存。
- **🧭 BI 级职业数据罗盘**：利用 Elasticsearch 引擎底座提供高并发聚合透视，支持省市穿透与一二级行业细分画像，并配合前端 ECharts 即时生成宏观薪资漏斗及岗位技能池云图展示。
- **🧱 企业级高可用体系与架构隔离**：拥有自动化 Hash 对象生成 `@cache` 装饰器与底层深度的分布互斥锁。彻底解耦 Pydantic Data Schema 验证层与底仓逻辑，以极强的数据洁癖防御渗透。
- **🛡️ 立体化网关安全防线 (Security Gateway)**：从底层的 HTTP HSTS / Anti-MIME 嗅探保护头封装，到直连 Redis 无僵尸键的极致 Lua 原子操作限流器，辅以应用层中间件直截 SQLi / XSS 的过滤黑名单探针封禁，护航银行级访问安全。
- **⚡ 弹性基础设施**：Circuit Breaker 熔断器（5 次失败→60s 自动熔断恢复）+ AI 结果级 Redis 缓存（career_advice 24h / career_compass 12h）+ Celery 双队列物理隔离，全异步 AI 体验，轮询/WebSocket 自由回射结果不阻塞主线程。
- **🔒 AI 任务并发管控**：每用户每接口 Redis 原子锁 + AiTask 持久化模型 + 请求去重缓存（MD5 摘要 1h TTL）+ 僵死任务 Celery Beat 自动清理，构建企业级 AI 任务全生命周期管理闭环。
- **🔔 实时 AI 任务通知**：后端 Celery Worker → Redis Pub/Sub → WebSocket → 前端 Pinia Store + ElNotification，用户无需停留在页面即可收到 AI 任务完成/失败推送通知。
- **📈 Prometheus + Grafana 全景监控**：自动暴露 `/metrics` 端点（HTTP RED + 18 项自定义业务指标），预置 Grafana 看板（熔断器状态/AI 缓存/计费/Celery 趋势/AI 任务生命周期），Docker 一键启动零配置。

## 🛠️ 技术栈清单

- **后端核心**: `Python` · `FastAPI`
- **安全与控制**: `SecurityMiddleware` (WAF/Helmet) · `Lua 原子限流` · `AppException 捕获`
- **前端架构**: `Vue 3` · `Vite` · `ECharts` · `Element Plus` · `Pinia` (AI 任务全局 Store)
- **中台与爬虫**: `Starlette-Admin` · `Scrapy`
- **任务分发**: `Celery` (双队列: realtime / batch) · `Redis`
- **持久层与引擎**: `PostgreSQL` (基于 asyncpg & SQLAlchemy 2.0) · `Elasticsearch`
- **AI 解析**: `LangChain Core` · `Pydantic` Schema
- **微服务高可用**: Circuit Breaker · 多层拦截缓存锁 · Redis 并发锁 · 去重缓存 · uvicorn M-Worker
- **可观测性**: Prometheus (18 项指标) · Grafana (18 面板) · Loguru

## 🚀 快速启动

```bash
# 1. 启动后端 (开发模式)
cd jobCollectionWebApi
.\run_api_dev.bat

# 2. 启动 Celery Worker (双队列)
.\run_worker.bat             # batch 队列 (岗位解析/ES同步/代理)
.\run_worker_realtime.bat    # realtime 队列 (AI 实时任务)

# 3. 启动定时调度
.\run_beat.bat

# 4. 生产部署 (多 Worker)
.\run_api_prod.bat           # 4 个 uvicorn Worker

# 5. 启动监控 (Docker)
docker-compose up -d prometheus grafana
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (admin/admin)
```

## 📖 详细文档

- 系统架构蓝图与功能模块全景：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 迭代大纲与设计变更全记录：[`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md)

---
*Developed with ❤️ and Python.*
