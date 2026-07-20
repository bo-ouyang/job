# Batch 7：测试、监控和部署验证

## 目标

建立 Agent 的后端、前端、SSE、迁移、可观测性和代理层质量门槛。

## 依赖

- Batch 1-6 的功能代码已完成。
- 已有 staging PostgreSQL、Redis、Elasticsearch、Celery 和 Nginx 环境。

## 后端测试文件

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

- migration 空库/已有库。
- owner check 和资源隔离。
- 状态转换、终态保护和幂等提交。
- 工具输入、统一输出、ES 降级和双失败。
- 模型失败、超时、熔断和工具上限。
- Redis 事件顺序、重放和重复派发。
- SSE 断线、heartbeat、重连和取消。

## 前端测试

当前前端没有测试框架。本批引入：

- Vitest。
- `@vue/test-utils`。
- jsdom。
- SSE parser、Agent store 和关键组件测试。

最少覆盖：

- SSE 帧解析。
- 事件去重和增量消息。
- 重连退避。
- 刷新恢复。
- 取消和终态展示。
- 认证过期处理。

## 监控指标

在 `jobCollectionWebApi/core/metrics.py` 增加：

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

标签只能使用低基数维度，如 `status`、`tool_name`、`source`、`failure_kind`，禁止 user_id、run_id 和 prompt。

## 配置

修改：

```text
jobCollectionWebApi/config.py
.env.example
```

增加 Agent 开关、并发、工具超时、运行超时、事件 TTL、锁 TTL、heartbeat 和 Token 预算配置。

## Nginx/SSE 验证

修改：

```text
deploy/nginx/job.conf
```

确认：

- `proxy_buffering off`。
- `proxy_cache off`。
- `proxy_read_timeout` 大于一期最大运行时间。
- 保留 Authorization。
- `X-Accel-Buffering: no`。
- GZip 不缓冲 `text/event-stream`。
- SSE 不依赖 WebSocket upgrade。

## 发布验证顺序

1. 验证 migration。
2. 执行后端测试。
3. 执行前端测试和 `npm run build`。
4. 直连 Uvicorn 验证 SSE。
5. 通过 Nginx 验证 SSE。
6. 验证网络中断、刷新、取消和用户隔离。
7. 验证旧 AI、WebSocket、首页和简历功能。

## 验收标准

- 后端和前端测试通过。
- 空库和已有库 migration 通过。
- 通过 Nginx 的 SSE 事件逐条到达。
- 指标能区分 Agent 成功、失败、取消、工具错误和重连。
- 发布包不包含密钥、上传文件和运行时缓存。
