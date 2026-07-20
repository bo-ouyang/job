# 职业规划 Agent 重构总路线图

## 1. 文档目标

本文将项目从“多个独立 AI 功能”重构为“市场数据首页 + 职业规划 Agent”的整体目标拆分为可交付阶段。

本文只定义方向、边界、阶段目标和依赖关系。具体工程执行以《职业规划Agent详细实施计划.md》为准，一期产品范围以《职业规划Agent一期MVP产品与技术方案.md》为准。

## 2. 产品目标

最终产品由两个核心区域组成：

1. **就业市场首页**：展示客观、可追溯的职位和市场统计，不由 Agent 生成。
2. **职业规划 Agent**：用户用自然语言描述自身情况和目标，Agent 主动理解、追问、查询数据、分析差距并形成可持续更新的行动计划。

产品核心交互从以下模式迁移：

```text
选择功能 -> 填写表单 -> 调用固定接口 -> 等待报告
```

迁移为：

```text
描述目标 -> Agent 理解 -> Agent 选择工具
-> 查询真实市场数据 -> 实时输出阶段进展
-> 形成职业画像和行动计划 -> 后续持续跟进
```

## 3. 明确不做的事情

第一阶段及中期内不做以下事项：

- 不把首页统计改造成 LLM 生成内容。
- 不允许模型直接访问数据库、Redis 或 Elasticsearch。
- 不用 Agent 替代确定性的支付、收藏、投递和权限逻辑。
- 不继续为每一种职业问题新增一个固定 AI endpoint。
- 不在第一期实现多 Agent 协作、自动投递、自动联系招聘方。
- 不把所有历史 AI 任务一次性迁移为对话消息。

## 4. 目标架构

```text
Vue Agent 工作台
    |
    | SSE 实时事件流
    v
Agent API / Runtime
    |
    +-- 会话与职业画像
    +-- Agent 状态图
    +-- 工具注册与参数校验
    +-- 模型调用与熔断
    +-- 预算、超时、循环限制
    |
    +-- Search Tools ------> Elasticsearch / PostgreSQL
    +-- Analysis Tools ----> AnalysisService
    +-- Profile Tools -----> PostgreSQL
    +-- Resume Tools ------> PDF / AI parser
    +-- Plan Tools ---------> PostgreSQL
    |
    +-- Celery ------------> 长耗时任务
    +-- Redis --------------> 缓存、checkpoint、事件和锁
```

原则：

- Agent 负责理解、规划、选择工具和综合结论。
- 工具负责查询、计算、写入和外部副作用。
- 所有工具必须有明确输入 Schema、输出 Schema、权限和超时。
- 所有关键结论尽可能绑定工具证据、样本量和数据时间。

## 5. 分阶段路线

### Phase 0：边界冻结与安全基线

目标：在写新 Agent 之前，冻结产品边界，避免继续堆叠旧 AI 页面。

交付物：

- 首页保留功能清单。
- Agent 工作台 MVP 需求。
- 旧 AI 功能到新 Agent 工具的映射表。
- 权限、上传、Token 和敏感数据风险清单。
- 现有 API 和测试的兼容策略。

完成标志：产品入口和一期范围不再发生歧义。

### Phase 1：Agent MVP

目标：用户输入一段自然语言，Agent 能实时完成一次基于真实岗位数据的职业分析。

能力范围：

- 创建会话和发送消息。
- 维护基础职业画像。
- 理解用户目标和缺失信息。
- 调用职位搜索、市场统计、技能需求工具。
- SSE 实时返回 Agent 事件。
- 输出候选方向、证据、差距和下一步行动。
- 保存会话和 Agent 运行记录。

暂不包含：复杂简历解析、长期提醒、自动投递和多 Agent。

### Phase 2：职业画像与计划闭环

目标：Agent 不只回答一次问题，而是持续记住用户状态。

能力范围：

- 简历解析结果进入职业画像。
- 用户确认或修正画像字段。
- 保存目标方向、约束和偏好。
- 生成学习计划和求职计划。
- 支持计划进度更新和阶段复盘。
- Agent 根据新信息重新评估方向。

### Phase 3：深度 Agent 推理

目标：让 Agent 能自主拆解复杂问题并进行多步工具调用。

能力范围：

- LangGraph checkpoint 和可恢复执行。
- 规划、工具执行、证据评估、二次查询循环。
- 信息不足时进行最少量追问。
- 工具失败重试和降级。
- 用户主动取消、暂停和恢复运行。
- 运行轨迹可观测和可回放。

### Phase 4：主动职业陪伴

目标：从“用户问 Agent 答”升级为“Agent 持续帮助用户行动”。

能力范围：

- 定期检查行动计划。
- 根据市场变化更新建议。
- 监控目标岗位变化。
- 生成周报和阶段总结。
- 结合收藏、投递和面试结果调整建议。

## 6. 现有代码迁移策略

### 保留并工具化

```text
services/search_service.py
services/analysis_service.py
crud/job.py
crud/industry.py
crud/major.py
services/ai_service.py 的模型调用能力
PostgreSQL / Redis / Elasticsearch 基础设施
Celery 长任务能力
```

### 重构

```text
api/v1/endpoints/ai_controller.py
    -> 收敛为 Agent 会话、消息和运行接口

services/ai_service.py
    -> 保留 LLM client、结构化输出和基础缓存

frontend/src/stores/aiTask.js
    -> 增加 Agent 会话、事件流和运行状态
```

### 逐步降级或移除入口

```text
/major-analysis
/career-compass
独立的 AI advice 表单
独立的 AI resume parse 交互
```

这些能力不必立即删除，先改为 Agent 内部工具，等新入口稳定后再下线旧页面。

## 7. 关键架构决策

### 实时协议

一期优先使用 SSE：

- 适合服务端持续输出。
- 与现有 REST 鉴权方式一致。
- 部署和重连比 WebSocket 简单。
- 不需要把 JWT 放到 WebSocket URL 中。

现有 WebSocket 保留用于消息中心和后台通知，Agent 对话流不再依赖它。

### 异步策略

- 普通对话和短工具调用：Agent Runtime 直接执行并流式返回。
- 简历解析、大规模分析和超时任务：提交 Celery，实时流返回任务事件。
- Agent 不能因为使用 Celery 就只返回一个最终报告。

### 数据真实性

Agent 的事实性结论必须优先来自工具结果。

每个市场类工具结果至少包含：

```text
data
sample_size
filters
data_as_of
source
warnings
```

## 8. 成功指标

产品指标：

- 用户首次输入后能否在一轮或两轮内得到可执行建议。
- Agent 建议是否包含真实岗位证据。
- 用户是否完成至少一个行动计划。
- 用户是否继续在同一会话中补充信息。

工程指标：

- 首个流式事件延迟小于 2 秒。
- 普通 Agent 运行 P95 小于 30 秒。
- 工具调用失败有明确降级结果。
- 每次运行都有可追踪的状态和事件。
- Agent 不产生未授权的数据写入。
