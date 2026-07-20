# 职业规划 Agent 工具契约与数据模型

## 1. 工具设计原则

Agent 工具是受控的业务能力，不是给模型开放的数据库接口。

每个工具必须定义：

- 工具名称和用途。
- 输入参数 Schema。
- 输出 Schema。
- 权限要求。
- 超时时间。
- 是否允许重试。
- 是否产生副作用。
- 数据来源和时间。
- 失败时的可解释信息。

工具返回的数据应尽量结构化，模型只负责解释和综合，不负责猜测缺失数据。

## 2. 通用工具输出

```json
{
  "ok": true,
  "data": {},
  "sample_size": 0,
  "filters": {},
  "data_as_of": "2026-07-20T00:00:00+08:00",
  "source": "elasticsearch",
  "warnings": []
}
```

失败时：

```json
{
  "ok": false,
  "data": null,
  "sample_size": 0,
  "filters": {},
  "data_as_of": null,
  "source": "elasticsearch",
  "warnings": ["职位搜索服务暂时不可用"]
}
```

## 3. 一期工具契约

### `search_jobs`

用途：根据职业目标、城市、行业和技能查找岗位样本。

输入：

```json
{
  "keyword": "数据分析",
  "cities": ["杭州"],
  "industries": [],
  "skills": ["SQL", "Excel"],
  "experience": null,
  "education": null,
  "salary_min": null,
  "salary_max": null,
  "limit": 20
}
```

约束：

- `limit` 最大 50。
- 关键词和城市数量有限制。
- 只读。
- 优先 Elasticsearch，失败后按统一格式降级 PostgreSQL。

输出重点：

```text
total
jobs
top_titles
top_cities
salary_summary
common_requirements
```

### `get_market_overview`

用途：获取某个职业方向的市场概览。

输入：

```json
{
  "keyword": "后端开发",
  "cities": ["杭州"],
  "industry": null,
  "time_range": "all"
}
```

输出重点：

```text
job_count
salary_distribution
education_distribution
experience_distribution
city_distribution
industry_distribution
```

### `get_skill_demand`

用途：统计目标岗位的技能需求和技能共现关系。

输入：

```json
{
  "keyword": "数据分析",
  "cities": ["杭州"],
  "limit": 30
}
```

输出重点：

```text
skills: [{"name":"SQL","count":120,"ratio":0.64}]
skill_groups
noise_removed
sample_size
```

### `compare_cities`

用途：比较相同职业方向在不同城市的机会和薪资。

输入：

```json
{
  "keyword": "前端开发",
  "cities": ["杭州", "上海", "深圳"]
}
```

输出重点：

```text
city_metrics: [{
  "city": "杭州",
  "job_count": 0,
  "salary": {},
  "top_skills": []
}]
```

### `compare_industries`

用途：比较一个职业方向在不同行业中的机会。

输入：

```json
{
  "keyword": "产品经理",
  "industries": ["互联网", "制造业", "金融"]
}
```

### `get_major_directions`

用途：根据专业名称查找相关职业方向和行业映射。

输入：

```json
{
  "major_name": "英语",
  "cities": ["杭州"]
}
```

输出必须区分：

- 数据库已有映射。
- 基于职位样本推导的方向。
- 模型推测但缺少数据验证的方向。

## 4. 工具调用策略

Agent 首轮通常按以下顺序执行：

```text
理解用户目标
→ get_major_directions（有专业信息时）
→ search_jobs
→ get_market_overview
→ get_skill_demand
→ 综合方向和差距
```

只有用户明确提出比较问题时，才调用：

```text
compare_cities
compare_industries
```

工具之间不传递未经校验的自然语言大段文本，优先传递结构化字段。

## 5. 运行和会话模型

### `agent_conversations`

```text
id                  UUID / string
user_id             bigint
title               varchar
status              active / archived
summary             text nullable
created_at          timestamp
updated_at          timestamp
```

约束：

- 用户只能访问自己的会话。
- 归档不删除历史消息。
- `updated_at` 用于会话排序。

### `agent_messages`

```text
id                  UUID / string
conversation_id     UUID / string
role                user / assistant / tool / system
content             text
message_type        text
metadata            JSONB nullable
created_at          timestamp
```

`metadata` 可保存：

```text
tool_name
tool_call_id
citations
data_as_of
run_id
```

### `agent_runs`

```text
id                  UUID / string
conversation_id     UUID / string
user_id             bigint
status              queued / running / waiting_user / completed / failed / cancelled
goal                text
current_node        varchar
step_count          integer
state_snapshot      JSONB nullable
error_code          varchar nullable
error_message       text nullable
started_at          timestamp nullable
completed_at        timestamp nullable
created_at          timestamp
```

`state_snapshot` 仅保存可恢复的结构化状态，不保存密钥、完整 Prompt 或未经脱敏的外部响应。

### `career_profiles`

```text
id                  bigint
user_id             bigint unique
education           JSONB
skills              JSONB
experience          JSONB
preferences         JSONB
constraints         JSONB
goals               JSONB
confidence          JSONB
updated_at          timestamp
```

画像字段建议记录：

```json
{
  "value": "杭州",
  "source": "user_message",
  "confidence": 1.0,
  "confirmed": true,
  "updated_at": "..."
}
```

## 6. 一期不落库的状态

以下内容先保存在 AgentRun checkpoint 或 Redis 中：

- 当前工具调用参数。
- 工具中间结果。
- 当前计划节点。
- 尚未被用户确认的画像候选字段。
- SSE 事件序号。

只有用户明确确认或运行完成后，才写入长期职业画像。

## 7. 安全策略

- 工具层再次校验用户身份，不只依赖 Agent prompt。
- 一期所有工具只读。
- 所有工具参数使用 Pydantic 校验。
- 禁止模型生成 SQL、DSL 后直接执行。
- 限制每个用户并发 AgentRun 数量。
- 限制单次运行工具次数、Token、时长和费用。
- 错误消息不得暴露 SQL、内部路径、Prompt、API Key。
- 用户简历和画像数据默认按个人数据处理。
- 运行日志只保存摘要，避免保存完整敏感内容。

## 8. 可观测性字段

每次 AgentRun 至少记录：

```text
run_id
conversation_id
user_id
model
first_event_latency_ms
total_duration_ms
tool_call_count
tool_failures
input_tokens
output_tokens
estimated_cost
final_status
```

每个工具至少记录：

```text
tool_name
duration_ms
success
fallback_used
sample_size
```
