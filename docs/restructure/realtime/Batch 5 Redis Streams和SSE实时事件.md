# Batch 5：Redis Streams、SSE 和实时事件

## 目标

实现可实时观看、可断线重连、可重放且不会重复执行的 Agent 事件流。

## 依赖

- Batch 2 已有 AgentRun 和状态查询接口。
- Batch 4 已能产生 Runtime 生命周期事件。
- Nginx 和 GZip 中间件行为已纳入测试范围。

## 新增文件

```text
jobCollectionWebApi/agent/events.py
jobCollectionWebApi/agent/event_store.py
jobCollectionWebApi/agent/locks.py
jobCollectionWebApi/agent/sse.py
frontend/src/utils/sseClient.js
```

## Redis 设计

事件 Stream：

```text
{prefix}:agent:run:{run_id}:events
```

活跃运行锁：

```text
{prefix}:agent:user:{user_id}:active
{prefix}:agent:run:{run_id}:lock
```

规则：

- key 只通过统一方法加一次 prefix。
- 锁使用 `SET NX EX` 和随机 token。
- 释放使用 compare-and-delete Lua。
- 长运行支持续租。
- Stream 有最大长度和终态 TTL。

## 事件结构

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

事件类型：

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

## SSE 行为

```text
鉴权
-> 校验 run owner
-> 读取 Last-Event-ID 或 last_sequence
-> 重放历史事件
-> 读取新事件
-> heartbeat
-> terminal event 后关闭
```

响应必须包含：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

## 关键规则

- 建立 SSE 连接不会启动 Agent。
- 重连只恢复观察，不重新提交用户消息。
- 取消必须使用条件状态更新，不能覆盖已完成运行。
- 事件内容不得泄露 Prompt、SQL、内部路径、Token 或原始异常。
- `UnifiedResponseMiddleware`、GZip、访问日志和 Nginx buffering 必须有集成测试。

## 前端 SSE 客户端

- 使用 `fetch` 携带 Bearer Header。
- 使用 `AbortController` 取消。
- 解析 `id/event/data` 帧和 heartbeat。
- 记录最后事件 ID。
- 指数退避重连。
- 重连失败后查询运行状态，而不是重新提交。

## 验收标准

- 首事件延迟小于 2 秒。
- 断线重连可以继续事件。
- 重放不会造成前端重复消息。
- 终态必然收到完成、失败或取消事件。
- 通过 Nginx 验证事件不会被缓冲成一次性响应。
