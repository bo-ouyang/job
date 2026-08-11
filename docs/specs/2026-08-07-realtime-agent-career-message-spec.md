# 实时 Agent、职业分析与消息中心 Spec

日期：2026-08-07
状态：Draft for implementation
适用范围：前端与 `jobCollectionWebApi`；不包含爬虫代码或爬虫部署

## 1. 目标

本 Spec 定义三条用户链路的统一行为和技术契约：

1. 首页 AI 行业问数：提交后立即有可见反馈，并通过 SSE 逐步展示回答。
2. 职业分析：任务创建结果、已有任务、业务错误和运行状态必须准确展示。
3. 消息中心：用户能看到简历解析、职业分析的完成/失败通知，并能跳到对应结果。

## 2. 非目标

- 不修改爬虫实现、采集策略或 Cookie 管理。
- 不在第一阶段实现模型原生 token streaming。
- 不以 WebSocket/SSE 取代 PostgreSQL 中的持久化消息。
- 不改变“AI 成功完成后才扣费”的产品规则。
- 不在本次工作中重做整个 Agent 编排架构。

## 3. 总体原则

### 3.1 单一运行追踪器

首页、职业分析、Agent 工作区必须复用同一套前端运行追踪能力：

- SSE 为主；
- `Last-Event-ID` 断线续传；
- 按 `run_id + event_id + event` 去重；
- SSE 不可用时降级到 GET run 轮询；
- 终态后重新获取服务端消息/报告快照进行校准。

### 3.2 前端展示的是状态机，不是一个布尔 loading

统一 UI 状态：

| UI 状态 | 来源 | 推荐文案 |
| --- | --- | --- |
| `submitting` | POST 请求未返回 | 正在提交问题… |
| `queued` | run status/event | 已进入分析队列… |
| `running` | `run_started` | AI 正在分析… |
| `using_tools` | tool events | 正在查询市场数据… |
| `generating` | `message_started` | 已完成分析，正在组织回答… |
| `streaming` | `message_delta` | 正在回答… |
| `waiting_user` | `clarification_required` | 需要补充信息 |
| `completed` | `run_completed` + 最终快照 | 回答完成 |
| `failed` | `run_failed` | 展示服务端可读错误与重试动作 |
| `cancelled` | `run_cancelled` | 已取消 |

### 3.3 持久事实与实时信号分离

- Agent 消息、职业报告、通知记录以 PostgreSQL 为事实来源。
- SSE 负责单次 Agent run 的实时进度和正文增量。
- WebSocket 负责全站新通知提醒。
- 页面重载后必须仅依靠 HTTP + PostgreSQL 恢复完整状态，不能依赖曾经收到过的实时事件。

## 4. API 命名与错误契约

### 4.1 V2 JSON 命名

所有 `/api/v2/**` 响应使用 camelCase。职业分析提交成功的标准响应：

```json
{
  "conversationId": "8001",
  "runId": "9001",
  "status": "queued",
  "answer": null
}
```

前端页面不得直接兼容两套字段。`frontend/src/api/career.js` 应在 API 边界返回统一的领域对象：

```js
{
  conversationId: "8001",
  runId: "9001",
  status: "queued",
  answer: null
}
```

若为兼容过渡期读取 snake_case，应只存在于 API Adapter 内，并配置移除期限；组件内不得出现 `run_id` / `conversation_id` 分支。

同一规则适用于报告字段，例如页面使用 `createdAt`，不得在 V2 组件中读取 `created_at`。

### 4.2 统一错误响应

服务端业务错误维持：

```json
{
  "code": "AGENT_ACTIVE_RUN_EXISTS",
  "msg": "已有职业分析任务正在执行",
  "data": {
    "runId": "9001",
    "conversationId": "8001",
    "status": "running"
  }
}
```

前端提供全局 `extractApiError(error)`，输出：

```ts
type ApiErrorView = {
  code: string | number | null;
  message: string;
  data: Record<string, unknown> | null;
  httpStatus: number | null;
  retryable: boolean;
};
```

解析优先级：

1. `response.data.msg`
2. `response.data.detail`（字符串）
3. `response.data.detail.msg` / `response.data.detail.message`
4. `response.data.message`
5. JS `error.message`
6. 调用方提供的默认文案

不得向普通用户直接展示 Python 异常、SQL、堆栈或完整上游模型错误。

### 4.3 稳定 Agent 错误码

至少支持：

| 错误码 | 用户语义 | 可重试 |
| --- | --- | --- |
| `AGENT_ACTIVE_RUN_EXISTS` | 已有任务，恢复现有进度 | 否，直接恢复 |
| `AGENT_EVIDENCE_UNAVAILABLE` | 数据不足，建议调整筛选 | 是，修改条件后 |
| `AGENT_DEADLINE_EXCEEDED` | 整体运行超时 | 是 |
| `AGENT_LLM_TIMEOUT` | 模型调用超时 | 是 |
| `AGENT_DISPATCH_FAILED` | 任务派发失败 | 是 |
| `AGENT_CANCELLED` | 用户或系统取消 | 是 |
| `AGENT_VALIDATION_FAILED` | 模型结果未通过结构校验 | 是 |

组件不得创建与后端不一致的别名，例如只映射不存在的 `AGENT_TIMEOUT`。

## 5. 职业分析任务创建与幂等

### 5.1 同一幂等键

同一用户、同一会话、同一 `Idempotency-Key` 重试时，服务端返回同一个 `conversationId` 和 `runId`，不创建第二个任务，也不重复预授权或扣费。

### 5.2 不同幂等键但已有活动任务

当用户已经存在 `queued`、`running` 或 `waiting_user` 的同类职业分析任务时：

- HTTP 409；
- `code = AGENT_ACTIVE_RUN_EXISTS`；
- `data` 必须携带 `runId`、`conversationId` 和 `status`；
- 前端展示“已恢复正在进行的分析”，并连接该 run 的 SSE；
- 不显示“任务创建失败”。

### 5.3 创建成功后的页面行为

1. 收到 202 后立刻保存 `runId`、`conversationId`。
2. 显示 run banner。
3. 连接 SSE。
4. 页面刷新时，从 latest report/history 或 active-run API 恢复 run。
5. 完成后重新请求最新报告与 overview，不能只相信事件内临时正文。

## 6. Agent SSE 内容流协议

### 6.1 接口

沿用：

```http
GET /api/v1/agent/runs/{runId}/events
Accept: text/event-stream
Last-Event-ID: <redis-stream-id>
```

保持当前鉴权、连接数限制、事件回放和终态快照逻辑。

### 6.2 新事件

在现有事件枚举中新增：

```text
message_started
message_delta
```

事件 envelope 保持现有 Agent V1 契约，避免破坏已有客户端：

```json
{
  "event_id": "1723000000000-1",
  "sequence": 8,
  "event": "message_delta",
  "run_id": "9001",
  "conversation_id": "8001",
  "data": {},
  "created_at": "2026-08-07T10:00:00Z"
}
```

`message_started`：

```json
{
  "event": "message_started",
  "data": {
    "format": "markdown",
    "streamMode": "validated_markdown_chunks"
  }
}
```

`message_delta`：

```json
{
  "event": "message_delta",
  "data": {
    "delta": "## 推荐方向\n",
    "index": 0
  }
}
```

现有 `message_completed` 保留并扩展为最终校准事件：

```json
{
  "event": "message_completed",
  "data": {
    "message_id": "7001",
    "content": "完整 Markdown",
    "result": {},
    "deltaCount": 24
  }
}
```

### 6.3 顺序约束

正常成功 run 必须满足：

```text
run_started
...plan/tool events...
message_started
message_delta(index=0..n，严格递增)
message_completed
run_completed
```

规则：

- 每个 run 最多一个 `message_started`；
- `index` 从 0 开始严格递增；
- `message_completed.content` 是权威最终正文；
- 客户端收到 `message_completed` 后用完整正文校准本地 delta 拼接结果；
- 终态事件之后不得再发布 delta；
- 重放事件必须保留原 `event_id` 和顺序，不生成重复业务事件。

### 6.4 第一阶段的流式实现边界

第一阶段保持 `complete_structured()` 和 Pydantic 校验不变：

1. 模型完整生成结构化 `AgentAnswer`；
2. 校验成功；
3. 生成最终 Markdown；
4. 以不破坏 Unicode 和 Markdown 块为原则分块；
5. 发布 `message_started` 和多个 `message_delta`；
6. 保存 assistant message；
7. 完成 run；
8. 完成扣费；
9. 发布 `message_completed`、`run_completed`。

这属于“经过验证后逐步呈现”，不是模型 token 原生流。能力接口改为：

```json
{
  "supports_sse": true,
  "supports_message_delta": true,
  "message_stream_mode": "validated_markdown_chunks"
}
```

### 6.5 分块策略

- 优先按 Markdown 段落、列表项或句子边界切分；
- 单块建议 24～160 个 Unicode 字符；
- 不截断 surrogate pair、组合字符或 UTF-8 字节；
- 不人为 sleep 很长时间；可使用 20～60ms 的可配置节奏改善视觉连续性；
- 服务端吞吐压力高时允许合并块或零延迟发布；
- chunk pacing 不得占用数据库事务。

### 6.6 Redis/SSE 故障降级

- Redis 事件发布失败不能把已经成功的 AI 结果改成失败；
- 后端仍完成消息保存、run 终态和正确扣费；
- 前端 SSE 断开后先使用 `Last-Event-ID` 重连；
- 连续重连失败后切换轮询；
- 轮询发现 completed 后加载完整消息/报告；
- 页面必须标注“实时连接已中断，正在同步结果”，不能静默卡住。

## 7. 首页 AI 对话 UI

### 7.1 提交时立即插入两条本地消息

- 用户消息：立即显示，带 `pending` 状态，POST 成功后转为 accepted。
- assistant 占位消息：显示动画和当前阶段，不等待第一个轮询结果。

### 7.2 流式正文展示

- 收到首个 `message_delta` 后移除纯动画，开始追加 Markdown；
- 使用安全 Markdown renderer；禁止直接 `v-html` 输出未清洗内容；
- 高频 delta 通过 `requestAnimationFrame` 或 30～50ms 批处理更新，避免每个小块触发完整组件重排；
- 仅当用户视图已靠近底部时自动滚动；用户向上阅读时不强行抢滚动；
- 显示“有新内容”按钮供用户返回底部。

### 7.3 错误与重试

- 失败消息保留用户原问题；
- 显示服务端 `msg` 与“重新发送”按钮；
- 重试生成新的幂等键，除非是网络层不确定提交结果，此时应先用原键重放以确认；
- 未得到 completed 的回答不得表现为成功，也不得让用户误以为已收费。

## 8. 职业分析 UI

### 8.1 报告生成

- “重新分析”点击后展示状态 banner；
- 若恢复已有任务，文案为“已恢复正在进行的分析”；
- completed 后刷新最新报告和所有图表；
- failed 后保留上一份成功报告，错误显示在 banner，不清空历史有效内容；
- `waiting_user` 显示补充信息表单或明确引导，不能无限轮询。

### 8.2 职业顾问问答

与首页复用同一流式消息组件和运行追踪器。问答回答按 Markdown 渲染，不使用 `<pre>` 堆叠整段文本。

### 8.3 轮询降级

如果必须轮询，使用“请求结束后再 setTimeout 下一次”的串行方式，不使用 `setInterval(async ...)`，确保同一 run 最多一个在途请求。

## 9. 消息与通知领域模型

### 9.1 数据模型扩展

在现有 `messages` 基础上新增：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `category` | varchar/enum | `resume`、`career_analysis`、`billing`、`system` |
| `status` | varchar/enum | `processing`、`completed`、`failed`、`cancelled`、`info` |
| `action_type` | varchar/enum | `route`、`open_resume_result`、`open_career_report`、`retry`、`none` |
| `action_data` | JSONB | 路由、runId、taskId、reportId 等 |
| `source_type` | varchar | `agent_run`、`resume_task`、`ai_task` 等 |
| `source_id` | varchar | 源任务/运行 ID，按字符串保存避免 JS 精度问题 |
| `dedupe_key` | varchar | 通知幂等键 |

约束：

- `dedupe_key` 唯一；
- 对历史记录字段允许为空；
- 新代码不得继续向已废弃的 `action_param` 写 JSON 字符串；
- `action_data` 只允许预定义白名单字段，不能存访问令牌或敏感简历全文。

### 9.2 标准通知 API 视图

V2 消息响应使用 camelCase：

```json
{
  "id": "6001",
  "title": "职业分析已完成",
  "content": "你的杭州 · AI 产品经理分析报告已生成",
  "category": "career_analysis",
  "status": "completed",
  "isRead": false,
  "createdAt": "2026-08-07T10:00:00Z",
  "action": {
    "type": "open_career_report",
    "route": "/career-analysis",
    "params": {
      "runId": "9001"
    }
  },
  "source": {
    "type": "agent_run",
    "id": "9001"
  }
}
```

### 9.3 统一通知服务

建立唯一领域入口，例如：

```python
NotificationService.publish_task_terminal(
    user_id=...,
    source_type=...,
    source_id=...,
    feature=...,
    terminal_status=...,
    action=...,
)
```

职责顺序：

1. 使用 `dedupe_key` 幂等写 PostgreSQL；
2. 事务提交成功后发布 WebSocket `new_message`；
3. WS 发布失败记录日志和指标，但不回滚持久消息；
4. 重试任务不得生成重复通知。

禁止简历、旧 AiTask、新 AgentRun 各自拼装不同格式的消息。

### 9.4 触发矩阵

| 来源 | 终态 | 通知 |
| --- | --- | --- |
| Resume parse | completed | 简历解析完成，可查看/确认资料 |
| Resume parse | failed | 简历解析失败，可重试 |
| Career AgentRun | completed | 职业分析报告完成，可打开 `/career-analysis` |
| Career AgentRun | failed | 职业分析失败，显示原因，可重试 |
| Career AgentRun | cancelled | 职业分析已取消 |
| Market question | completed | 默认不产生全站消息，避免噪声；仅在产品配置开启时通知 |

## 10. 消息中心 V2 UI

### 10.1 页面状态

必须区分：

- loading：骨架屏；
- loaded + empty：真正暂无消息；
- error：错误文案 + 重试；
- loaded：消息列表；
- loadingMore：分页加载中。

### 10.2 筛选与内容

提供：

- 全部；
- 未读；
- 简历；
- 职业分析。

每条消息展示：状态图标、标题、摘要、时间、已读状态和明确动作按钮。失败消息不得只用颜色表达，需带文本“失败”。

### 10.3 动作路由

- 简历完成：`/my/resume`，携带安全的 task/result 标识；
- 职业分析完成：`/career-analysis`，携带 `runId` 或 report 标识；
- 不再跳转 `/career-compass` 或 `/major-analysis`；
- 后端提供的 route 必须经过前端路由白名单，不允许任意外链跳转。

### 10.4 实时一致性

收到 `new_message` 后：

1. 顶部未读数从服务端重新获取，不直接无条件 `+1`；
2. 若消息中心已打开，重新获取第一页或按服务端 ID 插入并去重；
3. 多标签页、WS 重连和重复事件不得造成未读数累加错误。

## 11. 计费一致性

成功路径的逻辑提交边界必须保证：

- 结构化结果有效；
- assistant 最终消息已保存；
- run 成功转为 completed；
- 扣费账本写入成功且带唯一业务引用；
- 重试不会重复扣费。

任何 failed、cancelled、deadline exceeded、LLM timeout、SSE 断开但后台最终失败的任务均不得扣费。

SSE/WS 发布不是扣费成功的前置条件；实时通道故障时，HTTP 最终快照和账本仍应保持正确。

## 12. 可观测性

新增或确认以下指标：

- `agent_sse_connections_active`
- `agent_sse_reconnect_total`
- `agent_message_delta_total`
- `agent_first_visible_feedback_seconds`
- `agent_first_delta_seconds`
- `agent_run_duration_seconds`
- `notification_persist_total{source,status}`
- `notification_publish_failed_total{channel}`
- `notification_deduplicated_total`

日志必须携带 `user_id`（可脱敏）、`run_id`、`conversation_id`、`event_id`、错误码；不得记录 token、密码、完整简历内容或完整提示词中的敏感资料。

## 13. 性能要求

- POST 返回后 200ms 内渲染 assistant 占位消息（不含网络响应时间）；
- 服务端收到有效任务后 1 秒内可通过 SSE/轮询看到 queued/running 状态；
- delta 批处理下，对话区更新不超过每秒 30 次 DOM patch；
- 单一页面同一 run 仅维持一个 SSE 连接或一个轮询器；
- 消息列表首屏最多加载 20～30 条，必须分页；
- 所有 timer、AbortController、WS/SSE 监听在组件卸载时释放。

## 14. 安全要求

- Markdown 必须经过安全渲染和 XSS 清洗；
- 消息动作路由使用白名单；
- ID 以字符串传前端，避免 Snowflake ID 精度丢失；
- 不在 URL path 中长期传 access token；现有 WebSocket token path 应单独迁移为短期票据或受支持的安全鉴权方式；
- 前端错误信息不泄露内部异常；
- SSE 只能访问当前用户拥有的 run。

## 15. 验收标准

### 15.1 首页 AI

- 提交后立即出现用户消息和“正在回答”占位气泡。
- UI 能显示至少 queued、running/using-tools、streaming、completed/failed。
- 回答以不少于 2 个 delta 分段显示（短答案允许服务端合并，但仍需 started/completed）。
- SSE 断线重连不重复正文；重连失败后轮询能拿到最终结果。
- 页面刷新后历史回答完整且格式正确。

### 15.2 职业分析

- 真实 camelCase 202 响应不再触发“缺少 run_id”。
- 后端返回 `msg=已有任务正在分析` 时，页面展示该信息并恢复现有 run。
- `AGENT_LLM_TIMEOUT` 等错误显示对应中文文案。
- completed 后报告和图表刷新；failed 时上一份成功报告保留。
- 不存在重叠轮询或卸载后的后台 timer。

### 15.3 消息中心

- 简历解析成功/失败各产生且只产生一条持久消息。
- 职业分析成功/失败各产生且只产生一条持久消息。
- 页面可区分加载、空、错误和正常列表。
- 点击完成通知可打开正确结果页。
- 页面打开期间收到新消息会更新列表和未读数。
- 多标签页/WS 重连不导致重复消息或未读数异常。

### 15.4 计费

- completed run 扣费一次。
- failed、cancelled、timeout run 扣费 0 次。
- 同一幂等键重试不重复创建 run、不重复扣费、不重复通知。
