# Batch 4：Agent Runtime 和状态机

## 目标

实现一次有边界、有证据、有终态的职业分析运行，让模型负责理解和编排，工具负责事实查询。

## 依赖

- Batch 2 已能创建和派发 AgentRun。
- Batch 3 至少完成 `search_jobs`、`get_market_overview` 和 `get_skill_demand`。

## 新增文件

```text
jobCollectionWebApi/agent/state.py
jobCollectionWebApi/agent/runtime.py
jobCollectionWebApi/agent/graph.py
jobCollectionWebApi/agent/prompts.py
jobCollectionWebApi/agent/policies.py
jobCollectionWebApi/agent/errors.py
jobCollectionWebApi/services/llm_client.py
```

## Runtime 状态

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

不得保存 API Key、完整 Prompt、原始 SQL/DSL 和未脱敏敏感原文。

## 状态节点

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

## 一期策略

- 信息不足进入 `waiting_user` 并发送澄清问题。
- 信息足够后至少调用一个真实市场工具。
- 默认顺序：专业方向、职位搜索、市场概览、技能需求。
- 只有比较问题才调用城市或行业比较。
- 证据不足最多调整参数重试一次。

## 执行限制

```text
最多 6 次工具调用
单个工具最多 8 秒
单次运行最多 60 秒
最多 2 轮澄清
模型 Token 和成本受配置约束
```

## LLM 抽取

从 `services/ai_service.py` 抽取模型客户端、结构化输出、超时、熔断和指标到 `services/llm_client.py`。错误必须使用类型化异常或失败结果，不能将 `❌` 字符串当成成功回答。

## 工作项

- [ ] 实现 Celery realtime Agent task。
- [ ] 实现运行 claim，只有成功 claim 的 worker 执行。
- [ ] 实现意图和职业画像候选字段抽取。
- [ ] 实现信息完整性判断。
- [ ] 实现工具选择和结果评估。
- [ ] 实现答案结构化输出。
- [ ] 实现超时、取消、模型异常和工具异常。
- [ ] 保存脱敏 checkpoint。

## 验收标准

- 完整输入能完成一次真实工具分析。
- 信息不足时能追问，不虚构关键事实。
- 模型或工具异常将运行标记为 `failed`。
- 达到限制后安全终止。
- Runtime 不能调用未注册工具或执行任意模型代码。
