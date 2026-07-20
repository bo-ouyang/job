# Batch 1：数据模型、迁移和安全 CRUD

## 目标

建立 Agent 会话、消息、运行和职业画像的持久化基础，并保证所有资源查询都按用户隔离。

## 依赖

- Batch 0 的 ID、状态机和画像写入策略已冻结。
- 已确认当前 Alembic head 和目标数据库的迁移状态。

## 新增文件

```text
common/databases/models/agent_conversation.py
common/databases/models/agent_message.py
common/databases/models/agent_run.py
common/databases/models/career_profile.py
jobCollectionWebApi/schemas/agent_schema.py
jobCollectionWebApi/crud/agent.py
alembic/versions/<agent_migration>.py
```

## 修改文件

```text
common/databases/models/__init__.py
common/databases/models/user.py
common/databases/PostgresManager.py
jobCollectionWebApi/main.py
```

## 数据模型

### `agent_conversations`

字段：`id`、`user_id`、`title`、`status`、`summary`、`created_at`、`updated_at`。

索引：`(user_id, status, updated_at)`、`(user_id, created_at)`。

### `agent_messages`

字段：`id`、`conversation_id`、`role`、`content`、`message_type`、JSONB metadata、`created_at`。

索引：`(conversation_id, created_at, id)`。

### `agent_runs`

字段：`id`、`conversation_id`、`user_id`、`status`、`goal`、`current_node`、`step_count`、`state_snapshot`、错误字段、时间字段及运行指标字段。

索引：`(user_id, status)`、`(conversation_id, status)`、`(conversation_id, created_at)`。

### `career_profiles`

字段：`id`、`user_id`、education、skills、experience、preferences、constraints、goals、confidence、时间字段。

约束：`user_id` 唯一，JSONB 字段保存带来源、置信度和确认状态的结构化值。

## 实施步骤

1. 使用现有 Core `Base` 和 Snowflake ID 创建模型。
2. 添加外键、唯一约束、索引和必要的状态约束。
3. 在模型注册、启动导入和 `create_tables()` 路径中注册模型。
4. 编写显式 Alembic migration，验证空库和已有库。
5. 编写 Pydantic 请求、响应和状态 Schema。
6. 实现 owner-scoped CRUD。
7. 使用条件更新实现状态转换和终态保护。

## 必须实现的安全规则

- 所有查询都带 `user_id` 条件。
- 不信任客户端传入的 `user_id`。
- `agent_runs.user_id` 必须与会话所有者一致。
- `completed`、`failed`、`cancelled` 不可被覆盖。

## 验收标准

- migration 在空数据库和已有数据库通过。
- 用户 A 无法读取、修改或取消用户 B 的资源。
- 重复请求不会产生无主运行。
- 模型能被 Alembic 正确发现。
- CRUD 单元测试通过。
