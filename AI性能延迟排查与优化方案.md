# AI 功能链路延迟排查与优化方案

## 1. 问题现象

你描述的是：

- AI 提供商接口很快返回（日志已看到 `200 OK`）。
- 但前端真正收到完成结果、数据库写入完成，要额外等待约 20-30 秒。

这类问题通常不在“AI 调用本身”，而在 **AI 返回后的后处理链路**。

---

## 2. 现有代码链路（基于当前项目）

关键链路如下：

1. 前端请求 `POST /api/v1/analysis/ai/advice` 或 `career-compass`
2. 后端在 [`jobCollectionWebApi/api/v1/endpoints/ai_controller.py`](./jobCollectionWebApi/api/v1/endpoints/ai_controller.py) 中用 `task.delay(...)` 提交 Celery
3. Celery 执行 [`jobCollectionWebApi/tasks/ai_tasks.py`](./jobCollectionWebApi/tasks/ai_tasks.py)
4. AI 返回后，任务继续串行执行：
   - `mark_completed` 写 PG + Redis（[`jobCollectionWebApi/crud/ai_task.py`](./jobCollectionWebApi/crud/ai_task.py)）
   - 写消息中心（`crud.message.create + commit`）
   - Redis Pub/Sub 推送，再由 [`jobCollectionWebApi/api/v1/endpoints/ws_controller.py`](./jobCollectionWebApi/api/v1/endpoints/ws_controller.py) 转发 WebSocket
5. 前端 [`frontend/src/stores/aiTask.js`](./frontend/src/stores/aiTask.js) 轮询/WS 更新状态

结论：你的“用户可见完成时刻”绑定在任务末尾，任何后处理慢，都会表现成 AI 快但结果慢。

---

## 3. 高概率原因（按优先级）

## 3.1 Celery 任务完成前做了过多串行后处理（最高概率）

位置：

- [`jobCollectionWebApi/tasks/ai_tasks.py`](./jobCollectionWebApi/tasks/ai_tasks.py)
- [`jobCollectionWebApi/tasks/resume_parser.py`](./jobCollectionWebApi/tasks/resume_parser.py)

当前 `career_*_task` 在 AI 返回后并不会立刻结束，而是继续串行执行：

- `mark_completed`（DB update + Redis）
- `set_dedup_cache`
- 消息中心入库 + `commit`
- WS 推送

前端轮询接口里 `AsyncResult(task_id)` 只有在任务函数完全 return 后才会变成 `SUCCESS`，所以用户感知会滞后。

## 3.2 队列路由与 worker 资源隔离不够硬（高概率）

位置：

- [`jobCollectionWebApi/core/celery_app.py`](./jobCollectionWebApi/core/celery_app.py)
- [`jobCollectionWebApi/api/v1/endpoints/ai_controller.py`](./jobCollectionWebApi/api/v1/endpoints/ai_controller.py)

你依赖 `task_routes` 把任务路由到 `realtime`，但调用侧仍使用 `delay()`，没有显式 `queue="realtime"`。

当命名、导入路径、部署参数或 worker 队列消费配置出现偏差时，任务会回落到默认队列 `batch`（`task_default_queue="batch"`），造成排队延迟。

## 3.3 Redis 发布使用“每次新建连接”（中高概率）

位置：

- [`jobCollectionWebApi/tasks/ai_tasks.py`](./jobCollectionWebApi/tasks/ai_tasks.py)
- [`jobCollectionWebApi/tasks/resume_parser.py`](./jobCollectionWebApi/tasks/resume_parser.py)

`_publish_result/_publish_ws` 每次 `redis.from_url(...) -> publish -> close`。高并发或网络抖动时，这种短连接模式会额外增加耗时与不稳定性。

## 3.4 前端主要靠轮询，且间隔固定 2s（中概率）

位置：

- [`frontend/src/stores/aiTask.js`](./frontend/src/stores/aiTask.js)
- [`frontend/src/utils/pollTask.js`](./frontend/src/utils/pollTask.js)

默认 2 秒轮询不是 20-30 秒主因，但会扩大“可见延迟”。如果你的 WS 因证书问题间歇失效，这个现象会更明显。

## 3.5 结果载荷过大导致 DB 落库慢（中概率）

位置：

- [`jobCollectionWebApi/tasks/ai_tasks.py`](./jobCollectionWebApi/tasks/ai_tasks.py)

`result_data` 会写入 `report/es_stats/analysis_result` 等聚合数据。若对象较大，DB update/commit 耗时会明显上升，并直接阻塞任务完成。

---

## 4. 先做验证（避免盲改）

建议先打 5 个时间点日志（同一个 `task_id`）：

1. `enqueued_at`（API 提交）
2. `worker_start_at`
3. `ai_done_at`（AI 返回）
4. `persist_done_at`（mark_completed 后）
5. `ws_published_at`

这样可以把 20-30 秒精确拆到某一段。

另外在服务器核对：

1. `supervisorctl status` 是否同时有 `realtime` 和 `batch` worker
2. `celery inspect active_queues` 确认 AI 任务确实在 `realtime`
3. Redis 队列长度是否堆积
4. WS 是否稳定连接（浏览器 Console）

---

## 5. 修改方案（按阶段）

## Phase A：立刻见效（低风险）

1. API 提交任务改为显式队列：
   - `delay(...)` 改 `apply_async(kwargs=..., queue="realtime", routing_key="realtime")`
2. Celery 设置补充：
   - `worker_prefetch_multiplier=1`
   - `task_track_started=True`
3. 部署层确保独立 worker：
   - `realtime` 专门消费用户 AI 任务
   - `batch` 专门消费爬虫/ES/清理任务

## Phase B：核心改造（中风险，高收益）

目标：让“用户看到完成”不被消息中心等非关键动作阻塞。

1. `ai_tasks` 中顺序调整为：
   - 先 `mark_completed`（任务结果持久化）
   - 立刻 WS 推送 `ai_task_completed`
   - 再异步投递“消息中心写库”任务到 `batch`
2. 消息中心写库拆新任务（例如 `tasks.notification_tasks.create_ai_message`）
3. `result_data` 降载：
   - 只存最终文本和必要字段
   - 大体量分析对象改存 Redis（短期）或单独表（长期）

## Phase C：可观测性完善（长期）

1. Prometheus 新增分段耗时指标：
   - queue_wait_seconds
   - postprocess_seconds
   - ws_publish_seconds
2. `ai_tasks` 表新增链路时间字段（可选）：
   - `started_at/ai_done_at/notified_at`
3. Grafana 面板按 feature 展示 P50/P95/P99

---

## 6. 预期收益

按你当前现象，优先做 Phase A + B 后通常可把“AI 返回后到前端可见”的额外延迟从 20-30 秒降到：

- 常态 1-5 秒
- 高峰 5-10 秒

---

## 7. 建议执行顺序

1. 先加链路时间点日志，确认瓶颈段
2. 同步落地 Phase A（显式 realtime 队列 + worker 配置）
3. 再做 Phase B（后处理拆异步）
4. 最后补 Phase C 指标和看板

如果你同意，我可以下一步直接按 Phase A + B 给你提交一版最小改动代码（包含可回滚点）。

---

## 8. 提交任务到 AI 返回阶段（新增专项优化）

这一段的目标是缩短：

- `POST /analysis/ai/*` 提交后，到 worker 真正发起 LLM 请求的时间
- worker 发起 LLM 请求后，到拿到模型结果的时间

### 8.1 `career_compass` 在“入队前”做了较重计算

现状：

- 在 controller 内先做专业关系查询、行业分类、ES 聚合、缓存判断，然后才入队
- 位置：`jobCollectionWebApi/api/v1/endpoints/ai_controller.py`（`get_career_compass`）

优化建议：

1. 改为“两段式异步”
   - API 只做参数校验 + 鉴权 + 入队，立即返回 `task_id`
   - ES 聚合与报告生成放到 Celery 任务内部
2. 如果暂时不改结构
   - 先把 `es_stats` 计算结果缓存（短 TTL）
   - cache miss 才做 ES 聚合

收益：可显著降低“点击后等待开始”的体感。

### 8.2 Celery 入参体积偏大（序列化 + Redis 传输成本）

现状：

- 任务参数里直接带 `analysis_result/es_stats/skill_cloud_data` 这类大对象
- 位置：`ai_controller.py` 的 `apply_async(...)`

优化建议（强烈推荐）：

1. 使用“Payload 指针”模式
   - 大对象先存 Redis：`ai_payload:{task_id}`
   - Celery 只传 `task_id + payload_key`
2. worker 内再读 payload
   - 失败时可重试读取
   - 处理完及时删除或短 TTL 过期

收益：减少 broker 序列化耗时，降低排队与投递延迟抖动。

### 8.3 realtime 队列仍可能被重任务拖慢

现状线索：

- 日志中出现过 `missed heartbeat from realtime@...`
- 说明 worker 存在阻塞或压力峰值风险

优化建议：

1. 拆分实时队列
   - `realtime_advice`（轻任务）
   - `realtime_resume`（PDF 解析偏重）
2. 进程隔离
   - advice/compass 与 resume_parse 分开 worker
3. 保持公平调度
   - 维持 `worker_prefetch_multiplier=1`
   - Linux 下可加 `-Ofair`

收益：避免某类重任务把所有实时请求一起拖慢。

### 8.4 `generate_career_advice` 的引擎策略可进一步提速

现状：

- `engine=auto` 且 `AI_LANGGRAPH_ENABLED=true` 时，可能进入 LangGraph 多步流程
- 可能包含额外 ES 查询 + 多次 LLM 调用
- 位置：`jobCollectionWebApi/services/ai_service.py`

优化建议：

1. 低延迟场景默认 `classic`
   - 把 `auto` 策略改成“高峰期强制 classic”
2. LangGraph 仅对高价值请求启用
   - 例如管理员开关或白名单
3. 预热图编译与客户端
   - 应用启动时预构建 graph，减少首请求冷启动

收益：缩短 worker 到 LLM 返回的平均耗时和尾延迟。

### 8.5 Prompt 体积控制（直接影响 LLM 首 token 延迟）

现状：

- `career_compass` 把 `es_stats` 全量 JSON（且 `indent=2`）塞进 prompt

优化建议：

1. prompt 输入改为“摘要版 stats”
   - TopN 薪资、TopN 技能、TopN 行业、关键分位值
2. 去掉 `indent=2` 和冗余字段
3. 按 feature 设置 token 预算上限

收益：模型响应更快，成本更低，稳定性更好。

### 8.6 建议新增的分段指标（提交到 AI 返回）

新增指标：

1. `ai_queue_wait_seconds`：`submitted_at -> worker_started_at`
2. `ai_pre_llm_seconds`：`worker_started_at -> llm_request_start_at`
3. `ai_llm_roundtrip_seconds`：`llm_request_start_at -> llm_response_at`

触发告警建议：

1. `ai_queue_wait_seconds P95 > 2s`：扩容 realtime worker
2. `ai_pre_llm_seconds P95 > 1s`：排查 payload 与前置逻辑
3. `ai_llm_roundtrip_seconds P95 > 12s`：排查 provider 与 prompt 体积

### 8.7 推荐执行顺序（本阶段）

1. 先做 payload 指针化（收益高、侵入小）
2. 再做 `career_compass` 入队前逻辑下沉
3. 然后拆分 `realtime` 队列（advice/resume）
4. 最后做 LangGraph 策略分层与 prompt 瘦身
