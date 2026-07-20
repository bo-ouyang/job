# Batch 0：设计冻结和测试基线

## 目标

冻结一期 Agent 的产品边界、技术协议和测试基线，避免后续因 ID、状态机、SSE 或计费策略变化反复返工。

## 前置依赖

- 已阅读 `docs/restructure` 下的四份设计文档。
- 已确认首页继续保留客观市场数据分析。
- 已确认旧 AI 功能暂不立即删除。

## 必须冻结的决策

- 新表主键采用现有 `BigInteger + Snowflake`，对外序列化为字符串。
- AgentRun 状态：`queued`、`running`、`waiting_user`、`completed`、`failed`、`cancelled`。
- Runtime 使用 Celery `realtime` 队列执行。
- Agent 事件使用 Redis Streams，不使用 Pub/Sub 作为唯一事件源。
- SSE 使用 `fetch` 携带 Bearer Header，不把 Token 放入 URL。
- 一期默认不新增计费扣款。
- 长期职业画像只写入用户明确确认的字段。

## 工作项

- [ ] 建立 10 条 Agent 评估问题，覆盖方向选择、转行、城市比较、行业比较、信息不足和数据不可用。
- [ ] 整理旧 AI endpoint 到新 Agent 工具的映射。
- [ ] 确认 SSE 事件类型、事件 ID、sequence 和重放规则。
- [ ] 确认消息提交幂等键规则。
- [ ] 修复或隔离 `pytest/conftest.py` 中 MySQL/PostgreSQL 和旧路由问题。
- [ ] 增加 `AGENT_ENABLED` 与 `VITE_AGENT_ENABLED` 配置方案。

## 交付物

- Agent API 契约确认稿。
- AgentRun 状态转换表。
- SSE 事件协议确认稿。
- 评估问题集。
- 旧功能兼容矩阵。
- 测试 fixture 设计。

## 验收标准

- 产品、后端、前端使用同一套一期范围。
- 后续任务均能归属到 Batch 1-8。
- 不再新增独立职业分析 AI 页面。
- 所有关键决策写入文档，不依赖口头约定。
