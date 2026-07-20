# 职业规划 Agent 详细实施计划

## 1. 计划范围

本文是 `docs/restructure` 目录下现有设计文档的工程落地计划，目标是完成一期 Agent MVP：

```text
用户自然语言输入
-> 创建会话和运行
-> Agent 理解目标并选择工具
-> 查询真实职位和市场数据
-> SSE 实时输出执行过程
-> 返回职业方向、证据、差距和行动建议
```

本计划只覆盖一期 MVP 和上线前的必要基础设施，不包含简历深度解析、长期计划闭环、主动提醒、多 Agent、自动投递和旧 AI 功能立即下线。

## 2. 当前基线

当前仓库已有：

- PostgreSQL、Redis、Elasticsearch 和 Celery 基础设施。
- `SearchService` 职位搜索和 PostgreSQL 降级能力。
- `AnalysisService` 市场聚合、技能云和专业分析能力。
- `ComparisonAnalysisService` 城市/行业对比能力。
- `AIService` 的 ChatOpenAI、结构化输出、缓存、熔断和指标能力。
- Vue、Pinia、Axios、旧 AI 任务轮询和 WebSocket 通知。

当前仓库没有：

- Agent 会话、消息、运行和职业画像模型。
- Agent 工具注册表和统一工具契约。
- Agent Runtime 和状态图。
- 可重放的 Agent 事件存储。
- SSE Agent 事件流。
- Agent 前端工作台和专用 Pinia store。
- Agent 专用测试和前端测试基础设施。

## 3. 先决策再编码

以下决策在 Phase 0 必须锁定，后续不再反复修改。

### 3.1 ID 策略

采用现有项目的 `BigInteger + Snowflake`，不采用 UUID。

理由：

- 现有用户和业务表均以 `BigInteger` 为主。
- SQLAlchemy 关系、Alembic、CRUD 和前端均已有数字 ID 习惯。
- Redis key、URL 参数和权限查询可以复用现有模式。

对外接口仍将 ID 序列化为字符串，避免 JavaScript 精度问题。

### 3.2 AgentRun 状态机

```text
queued -> running
queued -> cancelled
running -> waiting_user
running -> completed
running -> failed
running -> cancelled
waiting_user -> running
waiting_user -> cancelled
```

状态转换必须由数据库条件更新保证，不能使用无条件的读后写。

### 3.3 Runtime 执行方式

一期使用 Celery `realtime` 队列执行 AgentRun，理由是：

- 现有项目已经具备 Celery Worker、Redis broker 和任务状态机制。
- 普通 HTTP 请求不应持有模型调用和工具调用。
- 后续可以将长任务和 Agent Runtime 统一纳入任务监控。

HTTP 接口只负责写入用户消息、创建运行并派发任务。SSE 只负责观察和重放事件，绝不触发运行。

### 3.4 SSE 事件存储

采用 Redis Streams，不采用 Pub/Sub 作为唯一来源。

推荐 key：

```text
{prefix}:agent:run:{run_id}:events
```

每个事件具有 Redis stream ID 和业务 `sequence`。运行结束后保留事件至少 24 小时，超过保留期时由数据库最终状态兜底。

### 3.5 SSE 鉴权

前端使用 `fetch` + `Authorization: Bearer` 读取流，不使用原生 `EventSource`。

原因：当前 Token 存储在 localStorage，原生 EventSource 无法设置 Authorization Header，不能为了方便把 Token 放到 URL 查询参数中。

### 3.6 一期计费

一期 Agent 默认不新增计费扣款，使用 `AGENT_ENABLED` 独立功能开关和内部成本指标。

如果产品要求立即计费，必须在 Runtime 提交前明确：

- 按运行还是按模型 Token 计费。
- 取消和失败是否退款。
- 重连是否绝不重复扣费。
- 去重命中是否收费。

在这些规则确定前，不复用现有 AI advice 的扣费逻辑。

### 3.7 职业画像写入

一期只保存用户明确确认的字段。模型从消息中抽取的信息先作为 `career_profile_draft` 保存在运行状态中，不自动覆盖长期画像。

## 4. 交付批次总览

- [Batch 0：设计冻结和测试基线](foundation/Batch%200%20设计冻结和测试基线.md)
- [Batch 1：数据模型、迁移和安全 CRUD](backend/Batch%201%20数据模型迁移和安全CRUD.md)
- [Batch 2：会话 API 和运行派发](backend/Batch%202%20会话API和运行派发.md)
- [Batch 3：工具契约和市场工具适配](backend/Batch%203%20工具契约和市场工具适配.md)
- [Batch 4：Agent Runtime 和状态机](backend/Batch%204%20Agent%20Runtime和状态机.md)
- [Batch 5：Redis Streams 和 SSE 实时事件](realtime/Batch%205%20Redis%20Streams和SSE实时事件.md)
- [Batch 6：前端 Agent 工作台](frontend/Batch%206%20前端Agent工作台.md)
- [Batch 7：测试、监控和部署验证](quality/Batch%207%20测试监控和部署验证.md)
- [Batch 8：灰度发布和旧功能共存](release/Batch%208%20灰度发布和旧功能共存.md)

依赖关系：

```text
Batch 0
  -> Batch 1
  -> Batch 2
  -> Batch 3
  -> Batch 4
  -> Batch 5
  -> Batch 6
  -> Batch 7
  -> Batch 8
```

Batch 1、Batch 3 可以在 Batch 2 进行基础设计后并行开发，但合并前必须通过 Batch 0 的契约冻结。

## 5. Batch 0：设计冻结与工程基线

### 目标

冻结协议、状态、权限和测试边界，避免进入实现后再重写基础模型。

### 工作项

- [ ] 将本文作为一期实施唯一执行顺序。
- [ ] 确认 ID、状态机、Redis Streams、Celery realtime 和 SSE fetch 方案。
- [ ] 确认一期不计费政策或补充计费规则。
- [ ] 确认职业画像只写入用户确认字段。
- [ ] 整理旧 AI endpoint 到 Agent 工具的映射。
- [ ] 建立至少 10 条 Agent 评估问题。
- [ ] 修复测试基线中的 `/api` 与 `/api/v1` 路径不一致。
- [ ] 将 `pytest/conftest.py` 从 `MysqlManager` 切换到应用实际使用的 PostgreSQL mock seam，或建立独立 Agent 测试 fixture。
- [ ] 增加 `AGENT_ENABLED`、`VITE_AGENT_ENABLED` 的设计说明。

### 交付物

- 本实施计划。
- 一期接口和 SSE 事件协议确认。
- Agent 评估集。
- 旧功能兼容矩阵。
- 测试 fixture 方案。

### 验收门槛

- 产品、后端、前端对一期范围无冲突解释。
- 后续开发不得新增独立职业分析 AI 页面。
- 所有后续 PR 都能标注所属 Batch。

## 6. Batch 1：数据模型、迁移和安全 CRUD

### 目标

建立可追踪、可恢复、严格隔离用户资源的持久化基础。

### 新增文件

```text
common/databases/models/agent_conversation.py
common/databases/models/agent_message.py
common/databases/models/agent_run.py
common/databases/models/career_profile.py
jobCollectionWebApi/schemas/agent_schema.py
jobCollectionWebApi/crud/agent.py
```

### 修改文件

```text
common/databases/models/__init__.py
common/databases/models/user.py
common/databases/PostgresManager.py
jobCollectionWebApi/main.py
alembic/versions/<new_agent_migration>.py
```

### 实施顺序

1. 创建四个 SQLAlchemy 模型，统一使用现有 Core `Base` 和 Snowflake ID。
2. 建立用户、会话、消息、运行之间的外键和索引。
3. 在模型 `__init__.py`、Alembic、启动导入和 `create_tables()` 路径中注册模型。
4. 检查当前 Alembic head，确定新 migration 的 `down_revision`，禁止产生未经确认的多 head。
5. 编写显式 `op.create_table` migration。
6. 编写请求、响应和状态 Schema。
7. 实现 owner-scoped CRUD。
8. 实现运行状态的条件更新和终态保护。

### 必须实现的 CRUD

```text
create_conversation(user_id, ...)
list_conversations(user_id, ...)
get_conversation_for_user(conversation_id, user_id)
archive_conversation(conversation_id, user_id)
create_message(conversation_id, user_id, ...)
list_messages(conversation_id, user_id, ...)
create_run(conversation_id, user_id, ...)
claim_run(run_id, user_id)
get_run_for_user(run_id, user_id)
transition_run(run_id, from_statuses, to_status, ...)
cancel_run(run_id, user_id)
upsert_confirmed_profile(user_id, ...)
```

### 验收门槛

- 空数据库和已有数据库均可执行 migration。
- 用户 A 无法查询、修改、取消用户 B 的任何 Agent 资源。
- `completed`、`failed`、`cancelled` 运行不能被后续状态覆盖。
- 重复创建请求不会产生无主运行。
- `agent_runs.user_id` 与所属会话用户保持一致。

## 7. Batch 2：会话 API 和运行派发

### 目标

先打通不包含真实 Agent 推理的“创建会话 → 写消息 → 创建运行 → 查询状态”链路。

### 新增文件

```text
jobCollectionWebApi/api/v1/endpoints/agent_controller.py
```

可选的运行服务：

```text
jobCollectionWebApi/agent/runtime_dispatch.py
```

### 修改文件

```text
jobCollectionWebApi/api/v1/api.py
jobCollectionWebApi/config.py
.env.example
```

### API

```text
POST /api/v1/agent/conversations
GET  /api/v1/agent/conversations
GET  /api/v1/agent/conversations/{conversation_id}
POST /api/v1/agent/conversations/{conversation_id}/messages
GET  /api/v1/agent/runs/{run_id}
POST /api/v1/agent/runs/{run_id}/cancel
GET  /api/v1/agent/runs/{run_id}/events
```

Batch 2 只实现接口和占位运行，不接入完整模型推理。消息提交必须按以下事务顺序：

```text
校验会话归属
-> 写入 user message
-> 写入 queued AgentRun
-> commit
-> 派发 realtime task
-> 记录派发成功或失败
```

如果派发失败，运行应进入 `failed`，不能留下永久 `queued`。

### 幂等策略

消息请求增加客户端幂等键 `Idempotency-Key`，至少在 Redis 保留 10 分钟：

- 相同用户、相同会话、相同幂等键只返回原运行。
- SSE 重连不重新调用消息提交接口。
- 运行派发失败可以重试派发，但不能重复创建消息和运行。

### 验收门槛

- API 路由注册正确，统一前缀为 `/api/v1/agent`。
- 认证、owner check、错误格式和现有中间件兼容。
- 可以创建并查询 queued/running/failed/cancelled 状态。
- 旧 `ai_controller.py` 的路由和行为不被改变。

## 8. Batch 3：工具契约和市场工具适配

### 目标

把现有搜索和分析能力包装成只读、可校验、带来源和降级信息的 Agent 工具。

### 新增文件

```text
jobCollectionWebApi/agent/tools/base.py
jobCollectionWebApi/agent/tools/registry.py
jobCollectionWebApi/agent/tools/job_tools.py
jobCollectionWebApi/agent/tools/analysis_tools.py
jobCollectionWebApi/agent/tools/schemas.py
jobCollectionWebApi/agent/tools/normalizers.py
jobCollectionWebApi/agent/tools/resolvers.py
```

### 复用和修改范围

```text
jobCollectionWebApi/services/search_service.py
jobCollectionWebApi/services/analysis_service.py
jobCollectionWebApi/services/comparison_analysis_service.py
jobCollectionWebApi/crud/job.py
jobCollectionWebApi/crud/city.py
jobCollectionWebApi/crud/industry.py
jobCollectionWebApi/crud/major.py
```

### 工具上线顺序

1. `search_jobs`：建立统一职位结果形状。
2. `get_market_overview`：复用搜索过滤和聚合条件。
3. `get_skill_demand`：复用技能噪声清洗。
4. `get_major_directions`：加入专业映射和来源标记。
5. `compare_cities`：一期先支持 2 个城市。
6. `compare_industries`：一期先支持 2 个行业，验证父子行业语义后再扩展。

### 适配器必须解决的问题

- 城市名称到规范 code 的解析。
- 行业名称到 code、父行业和子行业的语义。
- 薪资单位统一。
- ES 与 PostgreSQL 返回字段统一。
- 搜索中的 industry 和 skills 过滤缺失。
- 市场分析中的 keyword、industry 和 city 过滤缺失或被忽略。
- 技能统计的 `count`、`ratio`、`sample_size` 和确定性排序。
- 城市/行业比较从双对象结果转换为 Agent 列表结果。
- 专业结果明确区分数据库映射、样本推导和未验证模型推测。

### 统一工具结果

每个工具必须返回：

```text
ok
data
sample_size
filters
data_as_of
source
warnings
```

工具内部可以使用现有 tuple 或旧 Schema，但离开工具边界前必须完成规范化。

### 验收门槛

- 所有工具输入均由 Pydantic 校验。
- 模型不能提供 SQL、ES DSL 或未注册工具名称。
- ES 失败时按工具契约降级 PostgreSQL，不能返回旧格式。
- 两端都失败时返回安全的 `ok=false`。
- 工具结果包含样本量、筛选条件、来源和数据时间。

## 9. Batch 4：Agent Runtime

### 目标

实现一次有边界、有证据、有终态的 Agent 分析运行。

### 新增文件

```text
jobCollectionWebApi/agent/state.py
jobCollectionWebApi/agent/runtime.py
jobCollectionWebApi/agent/graph.py
jobCollectionWebApi/agent/prompts.py
jobCollectionWebApi/agent/policies.py
jobCollectionWebApi/agent/errors.py
```

### Runtime 状态

只保存可序列化结构：

```text
run_id
conversation_id
user_id
intent
profile_candidates
plan
current_node
selected_tool
tool_arguments
tool_summaries
tool_call_count
clarification_count
event_sequence
deadline
token_usage
```

不保存 API Key、完整 Prompt、原始 SQL/DSL 和不必要的敏感原文。

### 状态节点

```text
load_context
understand_intent
extract_profile
check_completeness
ask_clarification
create_plan
select_tool
execute_tool
evaluate_evidence
compose_answer
save_result
```

### 一期执行策略

- 信息不足：发送 `clarification_required`，运行进入 `waiting_user`。
- 信息足够：至少调用一个真实市场工具。
- 默认执行：`get_major_directions`、`search_jobs`、`get_market_overview`、`get_skill_demand`。
- 比较类问题才调用城市或行业比较工具。
- 证据不足最多调整参数重试一次。

### 限制

```text
单次最多 6 次工具调用
单个工具最多 8 秒
单次运行最多 60 秒
最多 2 轮澄清
模型和 Token 预算由配置控制
```

### LLM 边界

从 `services/ai_service.py` 抽取：

```text
jobCollectionWebApi/services/llm_client.py
```

保留模型构造、结构化输出、熔断、超时和指标；将错误从“返回错误字符串”改为可捕获的类型化异常，避免错误被保存成成功回答。

### 验收门槛

- 完整输入可完成一次真实工具分析。
- 信息不足时能追问，不虚构关键事实。
- 工具、模型或数据库异常能进入 `failed`。
- 运行达到任一限制后安全终止。
- Runtime 只调用注册工具，不执行任意模型代码。

## 10. Batch 5：Redis Streams、事件和 SSE

### 目标

实现可实时观看、可重连、可重放、不可重复执行的 Agent 事件流。

### 新增文件

```text
jobCollectionWebApi/agent/events.py
jobCollectionWebApi/agent/event_store.py
jobCollectionWebApi/agent/locks.py
jobCollectionWebApi/agent/sse.py
frontend/src/utils/sseClient.js
```

### 事件结构

```json
{
  "event_id": "redis-stream-id",
  "sequence": 42,
  "event": "tool_completed",
  "run_id": "run-id",
  "conversation_id": "conversation-id",
  "data": {},
  "created_at": "..."
}
```

一期事件：

```text
run_started
plan_created
tool_started
tool_progress
tool_completed
clarification_required
message_delta
message_completed
run_completed
run_failed
run_cancelled
```

### Redis 约束

- 所有 key 通过统一方法只加一次 prefix。
- 每次运行使用 tokenized active lock。
- lock release 使用 compare-and-delete Lua。
- 运行超过 lock TTL 时续租。
- 事件 Stream 设置长度和终态 TTL。
- 禁止用 Pub/Sub 替代重放存储。

### SSE 行为

```text
鉴权
-> 校验 run owner
-> 读取 Last-Event-ID/last_sequence
-> 重放历史事件
-> 读取新事件
-> 定时 heartbeat
-> terminal event 后关闭
```

响应要求：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

需要验证 `UnifiedResponseMiddleware`、GZip 和请求日志中间件不会破坏 SSE；必要时在 SSE 路径做明确排除或特殊处理。

### 验收门槛

- 首个事件小于 2 秒。
- 断线重连不会创建新运行。
- `Last-Event-ID` 后可以继续重放。
- 终态必然收到 `run_completed`、`run_failed` 或 `run_cancelled`。
- 取消和完成竞态不会覆盖终态。

## 11. Batch 6：前端 Agent 工作台

### 目标

让用户不需要选择“专业分析”“职业罗盘”等功能，只需输入自然语言即可开始。

### 新增文件

```text
frontend/src/api/agent.js
frontend/src/stores/agent.js
frontend/src/views/AgentWorkspace.vue
frontend/src/views/AgentConversation.vue
frontend/src/components/agent/AgentShell.vue
frontend/src/components/agent/ConversationList.vue
frontend/src/components/agent/MessageTimeline.vue
frontend/src/components/agent/MessageComposer.vue
frontend/src/components/agent/RunStatusPanel.vue
frontend/src/components/agent/ToolExecutionCard.vue
frontend/src/components/agent/CareerProfileCard.vue
frontend/src/components/agent/DirectionCard.vue
frontend/src/components/agent/ActionPlanCard.vue
frontend/src/components/agent/ClarificationCard.vue
frontend/src/components/agent/AgentErrorState.vue
```

### 修改文件

```text
frontend/src/router/index.js
frontend/src/layout/BasicLayout.vue
frontend/src/assets/main.css
frontend/package.json
```

### Store 必须保证

- 一个运行只有一个活动 SSE 连接。
- 事件按 ID 或 sequence 去重。
- `message_delta` 增量拼接，`message_completed` 负责定稿。
- 断线先查询运行状态，不能重复提交消息。
- 终态清理重连定时器。
- 页面刷新后能恢复会话、运行和最终结果。
- 旧 `aiTask.js` 继续服务旧 Celery AI，不与 Agent store 混合。

### SSE 客户端

使用 `fetch` 流式读取：

- 携带 Bearer Header。
- 支持 AbortController。
- 解析 `id/event/data`。
- 支持 heartbeat。
- 记录最后事件 ID。
- 指数退避重连。
- Token 401 时按现有刷新逻辑处理。

### 验收门槛

- `/agent` 和 `/agent/:conversationId` 受登录保护。
- 桌面端支持三栏：会话、消息、画像/证据/行动。
- 移动端可用，输入框不被导航和底部栏遮挡。
- 页面能区分回答、工具状态、追问和错误。
- 旧首页和旧 AI 页面仍可用。

## 12. Batch 7：测试、监控和部署

### 后端新增测试

```text
pytest/test_agent_api.py
pytest/test_agent_permissions.py
pytest/test_agent_runtime.py
pytest/test_agent_tools.py
pytest/test_agent_events.py
pytest/test_agent_reconnect.py
pytest/test_agent_cancel.py
pytest/test_agent_migration.py
```

覆盖：

- 数据库 migration。
- owner check。
- 状态转换和终态保护。
- 幂等提交和重复派发。
- 六个工具的输入、输出、降级和错误。
- 模型失败和熔断。
- Redis 事件顺序和 replay。
- SSE 断线、重连、heartbeat、取消。
- 中间件对 SSE 的影响。

### 前端测试基础设施

前端当前没有测试框架。新增：

- Vitest。
- `@vue/test-utils`。
- jsdom。
- SSE parser、store 和关键组件测试。

### 指标

在 `jobCollectionWebApi/core/metrics.py` 增加低基数指标：

```text
agent_runs_created_total
agent_runs_completed_total
agent_runs_failed_total
agent_runs_cancelled_total
agent_run_duration_seconds
agent_first_event_latency_seconds
agent_tool_calls_total
agent_tool_failures_total
agent_sse_connections_active
agent_sse_reconnects_total
agent_lock_contention_total
```

禁止使用 user_id、run_id、prompt 作为 Prometheus label。

### 配置

修改：

```text
jobCollectionWebApi/config.py
.env.example
```

新增配置：

```text
AGENT_ENABLED
AGENT_MAX_CONCURRENT_RUNS_PER_USER
AGENT_MAX_TOOL_CALLS
AGENT_TOOL_TIMEOUT_SECONDS
AGENT_RUN_TIMEOUT_SECONDS
AGENT_MAX_CLARIFICATIONS
AGENT_EVENT_TTL_SECONDS
AGENT_EVENT_MAXLEN
AGENT_LOCK_TTL_SECONDS
AGENT_SSE_HEARTBEAT_SECONDS
AGENT_TOKEN_BUDGET
```

### Nginx

修改：

```text
deploy/nginx/job.conf
```

验证：

- `proxy_buffering off`。
- `proxy_cache off`。
- SSE read timeout 大于 60 秒。
- `X-Accel-Buffering: no`。
- 保留 Authorization。
- SSE 不使用 WebSocket upgrade 依赖。
- GZip 不缓冲 `text/event-stream`。

### 验收门槛

- 前后端构建成功。
- migration 在空数据库和已有数据库均验证。
- Agent 测试通过。
- 前端 SSE、刷新恢复和移动端测试通过。
- 通过 Nginx 实际验证流式事件，而不是只测 Uvicorn 直连。

## 13. Batch 8：灰度和旧功能共存

### 目标

在不影响旧用户的情况下验证 Agent 的真实使用效果。

### 工作项

- [ ] 后端增加 `AGENT_ENABLED`。
- [ ] 前端增加 `VITE_AGENT_ENABLED` 或运行时能力接口。
- [ ] 只向灰度用户显示 Agent 导航。
- [ ] 旧 `/major-analysis`、`/career-compass`、简历解析和 `aiTask.js` 保持可用。
- [ ] 记录 legacy AI 和 Agent 的独立指标。
- [ ] 建立 Agent 运行失败的回退提示，但不自动重复提交。
- [ ] 灰度期间收集 10 条评估问题和真实用户反馈。

### 上线前烟囱测试

```text
登录
-> 进入 /agent
-> 创建会话
-> 输入自然语言
-> 观察 run_started
-> 观察工具和回答事件
-> 完成运行
-> 中断网络并刷新
-> 继续同一 run
-> 取消另一个 run
-> 验证用户资源隔离
-> 验证旧 AI 功能
```

### 退出条件

满足以下条件才能扩大灰度：

- 没有跨用户数据读取。
- 没有重复运行或重复扣费。
- SSE 重连不会重复执行。
- 工具事实结果有来源、样本量和时间。
- 普通运行 P95 小于 30 秒。
- 首事件延迟小于 2 秒。
- 评估集中的问题均能产生可解释结果。

## 14. 推荐提交边界

```text
1. agent: freeze contracts and test fixtures
2. agent: add models and migration
3. agent: add owner-scoped CRUD and schemas
4. agent: add conversation APIs and dispatch
5. agent: add tool contracts and normalizers
6. agent: add search and market tools
7. agent: add comparison and major tools
8. agent: extract typed LLM client
9. agent: add runtime state machine
10. agent: add Redis Streams and SSE
11. frontend: add agent API, store and SSE client
12. frontend: add agent workspace and responsive layout
13. test: add backend and frontend Agent coverage
14. ops: add metrics, flags and Nginx SSE configuration
15. cleanup: deprecate legacy AI entrypoints after gray release
```

每个提交必须保持项目可启动；任何一批如果无法独立运行，应拆成模型/API、运行时、前端等更小提交。

## 15. 第一批实际开发顺序

接下来不直接改前端，也不直接重写 `ai_controller.py`。实际第一批按以下顺序执行：

1. 检查当前 Alembic head、数据库模型 Base 和 `User` 关系。
2. 新增四个 Agent 模型和 `agent_schema.py`。
3. 注册模型并编写 migration。
4. 为四个模型编写 owner-safe CRUD。
5. 增加 migration、模型和权限测试。
6. 验证后再进入会话 API。

第一批完成标志是：Agent 数据可以安全持久化、资源隔离和状态转换，尚不要求模型生成答案。
