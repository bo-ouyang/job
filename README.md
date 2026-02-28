<div align="center">
  <h1>🚀 Job Collection Platform</h1>
  <p><b>一个全栈架构的智能招聘数据采集、解析与后台管理平台</b></p>
</div>

## 📌 项目简介

本项目旨在打造一个高效的外部岗职位数据采集平台。主要针对主流招聘平台进行职位及公司信息的定向爬取，并通过大模型（LLM）对爬取到的**非结构化职位描述及简历进行自动化的特征重构与标签提炼**。

结合了先进的异步微服务架构设计，系统具备一套独立的权限后台管理体系、完整的可视化任务追踪以及可靠的反爬/死锁恢复机制。

## 🏗️ 核心架构

项目采用模块化拆分架构，主要分为三大领域：

1. **🚀 Web API (`jobCollectionWebApi`)**
   - 基于 **FastAPI** 的高性能异步核心引擎，支持 **uvicorn 多 Worker 生产部署**。
   - 提供完备的 RESTful API，用于内部数据流转及前端大盘展示。
   - 依赖 **PostgreSQL** 进行核心元数据层级化存储。
   - 原生支持 **Loguru** 全链路可视化日志与全局异常熔断接管。
   - 集成 **Circuit Breaker 熔断器**，防止 AI API 故障雪崩。

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
- **🧱 企业级高可用缓存防御体系**：集成自动化 Hash 对象生成 `@cache` 装饰器与底层深度的分布式 Redis 强互斥锁，兼具开发敏捷度与生产级的高并发防御（穿透/雪崩免疫）。
- **🛡️ AI 弹性基础设施**：Circuit Breaker 熔断器（5 次失败→60s 自动熔断恢复）+ AI 结果级 Redis 缓存（career_advice 24h / career_compass 12h）+ Celery 双队列物理隔离（realtime / batch），确保用户请求永远不被后台批量任务阻塞。
- **⚡ 全异步 AI 端点**：3 大 AI 接口（职业建议 / 罗盘报告 / AI 搜索）全链路 Celery 异步化，前端通过 WebSocket 实时推送或 HTTP 轮询获取结果，不再阻塞。

## 🛠️ 技术栈清单

- **后端层**: `Python` · `FastAPI` · `Scrapy`
- **前端层**: `Vue 3` · `ECharts` · `Element Plus`
- **管控中台**: `Starlette-Admin`
- **任务分发**: `Celery` (双队列: realtime / batch) · `Redis`
- **持久层**: `PostgreSQL` (基于 asyncpg & SQLAlchemy 2.0) · `Elasticsearch`
- **大模型解析**: `LangChain Core` · `Pydantic`
- **弹性架构**: Circuit Breaker · Redis 结果缓存 · uvicorn 多 Worker

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
```

## 📖 详细文档
如需查看系统的迭代大纲、设计变更与架构剖析全记录，请参见随附的  [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md)


---
*Developed with ❤️ and Python.*
