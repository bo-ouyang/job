# 职业规划 Agent 一期 MVP 产品与技术方案

## 1. 一期目标

一期只验证一个核心闭环：

```text
用户自然语言描述 -> Agent 实时分析 -> 查询真实岗位数据
-> 输出职业方向、市场证据、能力差距和行动建议
```

一期不是完整的长期职业陪伴系统，重点是验证 Agent 是否比固定表单 AI 更自然、更准确、更有行动价值。

## 2. MVP 用户场景

### 场景 A：不知道方向

```text
我是计算机专业大三学生，会 Python 和一点 Vue，不知道该找什么岗位。
```

Agent 应：

- 识别用户阶段、技能和目标不确定性。
- 查询相关岗位。
- 给出 2 至 4 个候选方向。
- 比较岗位数量、薪资、城市、技能要求。
- 指出当前信息不足或技能差距。
- 给出下一步行动。

### 场景 B：有目标但不知道是否现实

```text
我想去杭州做数据分析，但只有 Excel 和基础 SQL，三个月能找到工作吗？
```

Agent 应：

- 查询杭州数据分析岗位样本。
- 提取常见技能和经验要求。
- 对比用户现有能力。
- 输出风险判断和三个月优先级计划。

### 场景 C：已有简历或经历

```text
我做过两年运营，想转产品经理，应该怎么准备？
```

一期可以先支持用户文字描述；简历上传作为第二阶段接入，不阻塞 MVP。

## 3. MVP 页面

新增：

```text
/agent
/agent/:conversationId
```

页面区域：

- 左侧：会话列表。
- 中间：消息、工具执行状态和最终分析。
- 右侧：当前识别出的职业画像、候选方向和行动建议。

首页继续保留市场大盘，不与 Agent 页面混合。

## 4. MVP 用户流程

```text
1. 用户进入 /agent
2. 输入自然语言描述
3. 前端创建会话并发送消息
4. 后端创建 AgentRun
5. Agent 输出 run_started 和 plan 事件
6. Agent 调用市场工具
7. 前端实时展示工具执行摘要
8. Agent 评估数据是否充分
9. 必要时追问，否则生成结论
10. 保存消息、运行结果和画像候选字段
11. 输出 follow_up_questions 或 next_actions
```

## 5. MVP 后端接口

### 创建会话

```http
POST /api/v1/agent/conversations
```

请求：

```json
{
  "title": "职业规划",
  "initial_context": {
    "major": "计算机科学与技术"
  }
}
```

响应：

```json
{
  "id": "conversation-id",
  "title": "职业规划",
  "status": "active"
}
```

### 发送消息并启动运行

```http
POST /api/v1/agent/conversations/{conversation_id}/messages
```

请求：

```json
{
  "content": "我是计算机专业大三学生，会 Python，不知道该找什么工作。"
}
```

响应：

```json
{
  "run_id": "run-id",
  "message_id": "message-id",
  "status": "running",
  "stream_url": "/api/v1/agent/runs/run-id/events"
}
```

### 获取事件流

```http
GET /api/v1/agent/runs/{run_id}/events
Accept: text/event-stream
```

### 查询运行状态

```http
GET /api/v1/agent/runs/{run_id}
```

### 查询会话

```http
GET /api/v1/agent/conversations
GET /api/v1/agent/conversations/{conversation_id}
```

### 取消运行

```http
POST /api/v1/agent/runs/{run_id}/cancel
```

## 6. SSE 事件协议

事件统一格式：

```text
event: run_started
data: {"run_id":"...","conversation_id":"..."}
```

一期事件类型：

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

工具事件只展示给用户可理解的摘要，不直接暴露内部异常、SQL、Prompt 或密钥。

## 7. MVP Agent 状态图

```text
接收消息
  -> 加载职业画像
  -> 理解用户意图
  -> 判断信息是否足够
       |-- 不足 -> 生成澄清问题 -> 等待用户
       |-- 足够 -> 创建分析计划
  -> 选择市场工具
  -> 执行工具
  -> 评估证据
       |-- 不充分 -> 调整参数并重试一次
       |-- 充分 -> 生成分析
  -> 提取画像候选字段
  -> 保存运行结果
  -> 输出行动建议
```

一期必须限制：

- 单次运行最多 6 次工具调用。
- 单个工具超时 8 秒。
- 单次运行总时长 60 秒。
- 最大追问次数 2 次。
- 不允许无限循环。

## 8. MVP 工具集合

一期只接入只读工具：

```text
search_jobs
get_market_overview
get_skill_demand
compare_cities
compare_industries
get_major_directions
```

工具契约见《职业规划Agent工具契约与数据模型.md》。

一期不接入写入工具，画像和会话保存由 Runtime 在运行结束后以确定性代码完成。

## 9. 后端模块拆分

建议新增：

```text
jobCollectionWebApi/agent/
    __init__.py
    router.py
    runtime.py
    graph.py
    state.py
    events.py
    prompts.py
    policies.py
    tools/
        base.py
        job_tools.py
        analysis_tools.py
```

建议新增数据访问模块：

```text
jobCollectionWebApi/crud/agent.py
common/databases/models/agent_conversation.py
common/databases/models/agent_message.py
common/databases/models/agent_run.py
common/databases/models/career_profile.py
```

现有 `services/ai_service.py` 只逐步抽出以下职责：

- LLM client 创建。
- 模型调用。
- 结构化输出解析。
- AI 缓存。
- 熔断和超时。

## 10. MVP 前端状态

新增 Pinia store：

```text
frontend/src/stores/agent.js
```

状态至少包含：

```text
conversations
activeConversation
messages
activeRun
runEvents
careerProfileDraft
connectionState
```

SSE 断线后使用 `GET /runs/{id}` 查询最终状态，不重新执行 Agent。

## 11. MVP 实施顺序

1. 定义数据库模型和 Alembic 迁移。
2. 实现会话、消息、运行 CRUD。
3. 实现 SSE 事件发布和断线恢复。
4. 将现有搜索和分析能力包装成只读工具。
5. 实现 Agent Runtime 的单轮状态图。
6. 实现前端 Agent 工作台。
7. 增加运行、权限、工具失败和重连测试。
8. 灰度验证后再接入简历和行动计划写入。

## 12. MVP 完成定义

以下全部满足才算一期完成：

- 用户可以只输入自然语言启动分析。
- Agent 至少调用一次真实市场工具。
- 前端能实时看到计划、工具和回答事件。
- Agent 能在信息不足时追问，而不是胡乱补全。
- 输出包含候选方向、市场数据、样本量和行动建议。
- 会话刷新后可以继续查看历史消息。
- SSE 断线不会重复执行运行。
- 工具异常时能明确告知数据不可用。
- 普通用户不能读取其他用户的会话和运行。
