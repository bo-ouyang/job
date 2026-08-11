# 前端 Agent、职业分析与消息中心问题审计报告

日期：2026-08-07
范围：`frontend` 与 `jobCollectionWebApi`（明确排除 `jobCollection` 爬虫实现）
性质：问题调查与根因报告；本文件不代表已完成修复

## 1. 执行摘要

本次排查确认了 5 个直接影响用户体验或功能正确性的核心问题：

| 优先级 | 问题 | 已确认根因 | 用户影响 |
| --- | --- | --- | --- |
| P0 | 职业分析任务已创建，前端却提示创建失败 | V2 响应按 camelCase 输出，页面读取 snake_case | 用户误以为付费/分析没有执行，并可能重复点击 |
| P0 | 后端业务错误没有展示 | 后端统一返回 `msg`，页面只读取 `detail` | “已有任务”“参数错误”等真实提示被通用错误覆盖 |
| P1 | 首页 AI 对话不能实时展示 | 首页只轮询运行状态；后端 SSE 没有正文 delta 事件 | 用户长时间只看到按钮“发送中”，不知道系统是否工作 |
| P1 | 职业分析完成状态不进入消息中心 | 新 V2 `AgentRun` 终态没有写入 `messages`，也没有发布消息通知 | 用户离开页面后无法得知报告完成或失败 |
| P1 | 消息中心无法正确跳转、失败时像空数据 | 消息模型缺少动作元数据；旧路由仍在使用；请求失败没有错误态 | 简历/职业分析结果不可发现，页面容易被误判为“空白” |

现有系统并非没有实时能力：Agent 已有 SSE 事件流、事件回放与断线游标，前端 Agent Store 也已有 SSE 客户端。当前缺口是首页和职业分析没有复用该能力，以及后端只推送运行生命周期事件，没有推送回答正文片段。

## 2. 调查范围与方法

### 2.1 已检查范围

- 首页 AI：`frontend/src/views/HomeView.vue`
- 职业分析：`frontend/src/views/CareerAnalysisView.vue`、`frontend/src/api/career.js`
- Agent 前端运行跟踪：`frontend/src/stores/agent.js`、`frontend/src/utils/sseClient.js`
- Agent API/SSE/Runtime：
  - `jobCollectionWebApi/api/v1/endpoints/agent_controller.py`
  - `jobCollectionWebApi/agent/events.py`
  - `jobCollectionWebApi/agent/sse.py`
  - `jobCollectionWebApi/agent/runtime.py`
  - `jobCollectionWebApi/services/llm_client.py`
- V2 序列化和职业分析服务：
  - `jobCollectionWebApi/schemas/v2/common.py`
  - `jobCollectionWebApi/schemas/v2/career.py`
  - `jobCollectionWebApi/services/v2/career_service.py`
- 消息中心与通知：
  - `frontend/src/views/MessageCenter.vue`
  - `frontend/src/layout/BasicLayout.vue`
  - `common/databases/models/message.py`
  - `jobCollectionWebApi/schemas/message_schema.py`
  - `jobCollectionWebApi/tasks/notification_tasks.py`
  - `jobCollectionWebApi/tasks/resume_parser.py`
  - `jobCollectionWebApi/tasks/ai_tasks.py`

### 2.2 明确未检查范围

- 未读取、未修改 `jobCollection` 爬虫实现。
- 未对爬虫任务、Cookie、调度或采集逻辑提出改动。
- 本轮未修改任何前后端业务代码。

## 3. 问题一：首页 AI 行业问数缺少实时反馈与流式正文

### 3.1 当前实际行为

`HomeView.vue` 的 `sendAiQuestion()` 创建 Agent 任务后调用 `pollMarketRun()`。该函数固定间隔查询 `/api/v1/agent/runs/{runId}`，直至终态后再整体加载历史消息。

页面在等待期间仅有以下反馈：

- 发送按钮从“发送问题”变成“发送中…”；
- 对话列表没有立即插入 assistant 占位消息；
- 不显示排队、检索市场数据、分析、组织答案等阶段；
- 不逐段显示回答正文。

因此，只要一次任务需要几十秒，用户看到的就是一个长时间不变化的按钮，容易判断为页面卡死。

### 3.2 已存在但未被首页使用的能力

后端已有：

- `GET /api/v1/agent/runs/{runId}/events` SSE 接口；
- Redis Stream 事件保存、回放和 `Last-Event-ID` 断线续传；
- `run_started`、`plan_created`、工具调用、澄清、完成、失败、取消等事件。

前端已有：

- `connectAgentEventStream()`；
- `stores/agent.js` 中的断线重连、事件去重、运行状态与 `isThinking`；
- Agent 工作区对生命周期事件的展示。

首页没有接入这些实现，而是维护了另一套轮询逻辑。

### 3.3 为什么已有 SSE 仍不能“流式回答”

`agent/events.py` 当前仅定义 `MESSAGE_COMPLETED`，没有 `MESSAGE_STARTED` 或 `MESSAGE_DELTA`。`AgentRuntime.execute()` 在结构化答案全部生成并保存后，才发布一次 `message_completed`。

`LLMClient.complete_structured()` 当前使用一次性结构化调用，而不是将模型 token 逐个转发。因此能力接口明确返回：

```json
{
  "supports_sse": true,
  "supports_message_delta": false
}
```

结论：当前 SSE 是“运行过程实时”，不是“回答内容实时”。

### 3.4 风险与修复边界

直接将模型原始 token 流式写入前端，会破坏现有结构化输出校验、最终 Markdown、持久化原子性和“仅成功后扣费”语义。第一阶段更安全的做法是：保持结构化生成不变，在结构化答案验证成功后，将最终 Markdown 分块发布为 delta；所有分块结束后再提交消息、运行终态和扣费。后续再评估真正的模型 token streaming。

## 4. 问题二：职业分析“任务创建失败”但后端已创建

### 4.1 根因：V2 字段命名契约不一致

`CareerSubmissionResponse` 的 Python 字段是：

```python
conversation_id
run_id
```

但它继承的 `V2Model` 配置了 `alias_generator=to_camel`，实际 JSON 字段是：

```json
{
  "conversationId": "8001",
  "runId": "9001",
  "status": "queued",
  "answer": null
}
```

`CareerAnalysisView.vue` 的报告和问答流程却读取：

```js
response.data?.run_id
response.data?.conversation_id
```

所以服务端已经返回 HTTP 202 并创建任务，前端仍会抛出“缺少 run_id”，再显示“任务创建失败”。这是确定性契约错误，不是异步任务偶发失败。

同类问题还包括最新报告时间：V2 `created_at` 会序列化为 `createdAt`，页面模板当前仍读取 `latestReport.created_at`。它不会阻止任务创建，但会导致“更新于”时间缺失，说明问题应在 API 边界整体修复，而不是只替换一个 `run_id`。

### 4.2 为什么自动化测试没有发现

`frontend/src/views/CareerAnalysisView.test.js` 的 API Mock 返回了 `run_id` 与 `conversation_id`，与真实 V2 序列化结果不一致。测试验证了一个不存在于生产 API 的响应格式，属于假绿测试。

### 4.3 次生风险

- 用户可能重复点击，创建或尝试创建多个任务；
- 即便后端通过并发准入阻止重复任务，前端仍将正确的 409 当成通用失败；
- 用户无法回到已经在执行的 run，丢失进度感知；
- 可能引发“是否重复扣费”的担忧，尽管实际扣费逻辑应以成功终态为准。

## 5. 问题三：后端错误提示没有正确展示

### 5.1 后端真实错误契约

`jobCollectionWebApi/main.py` 的全局 `AppException` 处理器返回：

```json
{
  "code": "业务错误码或状态码",
  "msg": "用户可读错误信息",
  "data": null
}
```

### 5.2 页面读取了错误字段

职业分析 catch 分支主要读取 `error.response.data.detail`，没有读取 `msg`。因此后端即使明确返回“任务已经创建”“已有任务正在分析”或其他业务原因，页面也会显示通用“任务创建失败”。首页也存在相同兼容性问题。

### 5.3 错误码映射也有漂移

页面新增的映射包含 `AGENT_TIMEOUT`，而 Agent 运行时实际使用的超时错误包括：

- `AGENT_DEADLINE_EXCEEDED`
- `AGENT_LLM_TIMEOUT`

即使字段读取修复，错误码不一致仍会导致友好文案无法命中。

### 5.4 运行状态处理不完整

职业分析轮询只把 `queued`、`running` 视为活动状态，没有完整处理 `waiting_user`。如果 Agent 请求补充信息，页面可能继续轮询却不给用户输入入口。

同时 `setInterval(async () => ...)` 可能在一次请求超过 3 秒时启动下一次请求，造成重叠轮询、响应乱序和页面状态回退。

## 6. 问题四：消息中心 UI 看不到或误显示为空

### 6.1 页面错误态缺失

`MessageCenter.vue` 请求失败时只写 `console.error`。对用户而言，接口失败与真正“暂无消息”的画面相同，没有：

- 明确错误提示；
- 重试按钮；
- 骨架加载与失败态区分；
- 分页或加载更多状态。

这可以直接解释“看不到 UI”或“页面空白”的感知。

### 6.2 页面依赖数据库中不存在的动作字段

页面点击消息时读取 `msg.action_param`，希望解析出任务 ID 和功能类型。但：

- `common/databases/models/message.py` 没有 `action_param` 列；
- `jobCollectionWebApi/schemas/message_schema.py` 中该字段已被注释。

即使消息本身显示出来，也不能稳定携带目标路由、任务 ID、报告 ID或恢复动作。

### 6.3 路由仍指向旧功能页

`routeForFeature()` 当前映射：

- `career_compass -> /career-compass`
- `career_advice -> /major-analysis`

当前 V2 职业分析入口是 `/career-analysis`。这会让旧通知跳到已废弃或不匹配的页面。

### 6.4 消息中心打开期间不会刷新列表

`BasicLayout.vue` 订阅 WebSocket 并更新顶部未读数，但消息中心组件本身只在挂载时加载一次。用户停留在消息中心时收到新消息，顶部数字可能变化，列表仍不变化。

## 7. 问题五：简历/职业分析完成通知链路不统一

### 7.1 简历解析旧链路

简历解析任务会调用 `save_ai_task_message()`，写入 `messages`，并发布：

- `new_message`
- `ai_task_completed`
- `ai_task_failed`

因此简历解析在部分路径上可以产生消息，但因为缺少动作元数据，无法稳定跳转到具体结果。

### 7.2 V2 职业分析新链路

V2 职业分析使用 `AgentRun`。运行完成或失败后发布 Agent SSE 事件，但没有调用统一消息服务写入 `messages`，也没有向消息中心 WebSocket 发布完成/失败通知。

所以用户离开职业分析页面后，报告即使完成，也不会在消息中心出现。

### 7.3 数据侧只读证据

本次只读检查得到：

- `messages_total = 15`，未读 1；
- `messages.created_at` 最大值为 2026-07-29 13:36:53；
- 历史简历通知 1 条、历史职业通知 5 条；
- 新 `AgentRun` 已有 completed 8、failed 13；
- Agent assistant `analysis_result` 已有 8 条。

这表明新 Agent 运行已经产生终态与回答，但消息表没有同步更新，符合代码路径调查结果。

## 8. 现有测试结论与覆盖缺口

排查阶段相关测试曾全部通过：

- 后端相关测试：35 passed；
- 前端相关测试：26 passed。

通过不等于上述问题不存在，覆盖缺口是：

1. 职业分析组件 Mock 使用错误的 snake_case，未覆盖真实 camelCase。
2. 首页测试只验证轮询完成，未要求 SSE、占位消息或正文 delta。
3. `MessageCenter.vue` 没有组件测试。
4. 没有验证 `AgentRun` 终态会生成持久通知。
5. 没有跨层契约测试验证 Pydantic Serializer 的真实 JSON 与前端读取字段一致。

## 9. 根因归类

这些问题不是三个孤立的 UI Bug，而是四类架构断层：

1. **API 契约断层**：V2 统一 camelCase，但局部页面仍按 snake_case 编写。
2. **运行追踪重复实现**：Agent 工作区已使用 SSE，首页和职业分析又各自实现轮询。
3. **通知领域断层**：旧 `AiTask`、简历解析和新 `AgentRun` 分别发送消息，没有统一通知出口。
4. **持久状态与实时信号混淆**：WS/SSE 应负责“及时提醒”，PostgreSQL 应负责“可恢复事实”；当前新 Agent 只有实时事件，没有消息中心持久事实。

## 10. 修复优先级建议

### 第一优先：先消除功能性错误

- 统一职业分析响应字段；
- 统一错误解析；
- 正确恢复已有活动任务；
- 补真实契约测试。

### 第二优先：补齐实时体验

- 为 Agent 增加 `message_started`、`message_delta`；
- 首页和职业分析复用同一套 SSE 追踪；
- SSE 失败时才降级轮询。

### 第三优先：建立统一通知

- 为消息增加分类、来源、动作和去重元数据；
- `AgentRun` 与简历解析都通过统一通知服务写库并发布 WS；
- 重做消息中心的错误态、筛选、跳转和实时刷新。

完整契约见 `docs/specs/2026-08-07-realtime-agent-career-message-spec.md`，实施顺序见 `docs/plans/2026-08-07-realtime-agent-career-message-plan.md`。
