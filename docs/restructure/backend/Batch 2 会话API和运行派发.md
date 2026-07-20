# Batch 2：会话 API 和运行派发

## 目标

打通“创建会话、发送消息、创建 AgentRun、查询运行状态”的后端链路，此阶段可以先使用占位 Runtime，不要求模型产生最终答案。

## 依赖

- Batch 1 的模型、migration、Schema 和 owner-safe CRUD 已完成。
- Agent API 和状态契约已冻结。

## 文件范围

新增：

```text
jobCollectionWebApi/api/v1/endpoints/agent_controller.py
```

修改：

```text
jobCollectionWebApi/api/v1/api.py
jobCollectionWebApi/config.py
.env.example
```

## API

```text
POST /api/v1/agent/conversations
GET  /api/v1/agent/conversations
GET  /api/v1/agent/conversations/{conversation_id}
POST /api/v1/agent/conversations/{conversation_id}/messages
GET  /api/v1/agent/runs/{run_id}
POST /api/v1/agent/runs/{run_id}/cancel
GET  /api/v1/agent/runs/{run_id}/events
```

SSE endpoint在 Batch 5 实现，本批先保留路由规划和运行状态查询。

## 消息提交事务

```text
校验会话归属
-> 写入 user message
-> 写入 queued AgentRun
-> commit
-> 派发 realtime task
-> 记录派发成功或失败
```

派发失败必须把运行转为 `failed`，不能遗留永久 `queued`。

## 幂等策略

- 接收 `Idempotency-Key`。
- Redis 保存用户、会话和幂等键到运行 ID 的映射。
- 相同幂等键只返回原运行。
- SSE 重连不重新调用消息提交接口。
- 运行派发重试不能重复写消息和运行。

## 工作项

- [ ] 注册 `/agent` router。
- [ ] 实现会话创建、列表、详情和归档。
- [ ] 实现消息提交和历史读取。
- [ ] 实现运行状态查询和取消请求。
- [ ] 所有接口加入 `get_current_user`、`get_db` 和 owner check。
- [ ] 统一使用项目当前响应封装和业务异常。
- [ ] 增加 Agent feature flag。

## 验收标准

- API 路由全部位于 `/api/v1/agent`。
- 未登录访问被拒绝。
- 用户资源隔离测试通过。
- 重复消息请求不会创建第二个运行。
- 旧 `ai_controller.py` 行为不受影响。
