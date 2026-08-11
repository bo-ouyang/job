# 实时 Agent、职业分析与消息中心实施 Plan

日期：2026-08-07
输入 Spec：`docs/specs/2026-08-07-realtime-agent-career-message-spec.md`
问题依据：`docs/specs/2026-08-07-frontend-agent-career-message-audit.md`
范围：仅前端和 `jobCollectionWebApi`，不得读取或修改 `jobCollection` 爬虫实现

## 执行约束

- 严格按 Phase 0 → Phase 6 顺序执行；每阶段通过检查点后再进入下一阶段。
- 每个 Bug/功能先写失败测试，再写最小实现，再运行相关回归测试。
- 保留现有未提交改动；开始前记录 `git status --short`，不得覆盖用户文件。
- 不提交、不推送，除非用户在实施会话中明确授权。
- PostgreSQL migration 必须向前兼容，禁止破坏或删除历史消息列。
- 第一版正文流使用“结构化结果验证后的 Markdown 分块”，不直接重写成模型 token streaming。

## Phase 0：冻结契约与建立失败基线

### 目标

在业务实现前，让自动化测试准确复现当前 4 个断层：camelCase、错误 `msg`、无正文 delta、无 AgentRun 通知。

### 已确认可复用 API / 模式

| 能力 | 参考实现 | 允许用法 |
| --- | --- | --- |
| V2 camelCase | `jobCollectionWebApi/schemas/v2/common.py` 的 `V2Model` | `/api/v2` 对外字段使用 alias 后的 camelCase |
| 职业提交 Schema | `jobCollectionWebApi/schemas/v2/career.py` 的 `CareerSubmissionResponse` | `conversationId`、`runId`、`status`、`answer` |
| Agent SSE | `jobCollectionWebApi/api/v1/endpoints/agent_controller.py:get_run_events` | 复用现有鉴权、限流与事件生成器 |
| SSE 回放 | `jobCollectionWebApi/agent/sse.py`、`event_store.py` | 使用 `Last-Event-ID` 和 Redis Stream ID |
| 前端 SSE 客户端 | `frontend/src/utils/sseClient.js:connectAgentEventStream` | 复用 fetch-stream、游标和 abort 机制 |
| 前端 Agent 追踪 | `frontend/src/stores/agent.js` | 复用事件去重、重连、run 状态更新 |
| 全局错误结构 | `jobCollectionWebApi/main.py:app_exception_handler` | `{code,msg,data}` |
| 简历/旧任务通知 | `jobCollectionWebApi/tasks/notification_tasks.py` | 仅作为现状参考，后续收口到统一通知服务 |
| 顶部实时提醒 | `frontend/src/layout/BasicLayout.vue` | WS 到达后触发服务端状态同步 |
| Nginx SSE 配置 | `deploy/nginx/job.conf`、`deploy/nginx/container.conf` | `proxy_buffering off`、足够的 read timeout |

### 实施任务

1. 修正 `frontend/src/views/CareerAnalysisView.test.js` 的 Mock，使其返回真实 `runId`、`conversationId`，确认当前测试先失败。
2. 新增后端 Serializer/API 契约测试，直接对 `CareerSubmissionResponse` 做 alias JSON 断言。
3. 为待新增的 `extractApiError()` 写表驱动测试，覆盖 `msg`、字符串 `detail`、嵌套 detail、网络错误与默认文案。
4. 为 `HomeView.vue` 写失败测试：提交后立即出现 assistant 占位；收到 started/delta/completed 后依次更新。
5. 为 `MessageCenter.vue` 建立组件测试：loading、empty、error、retry、list、action route。
6. 为 Agent Runtime 写失败测试：成功 run 发布 started → delta → completed；失败 run 不发布 completed。
7. 为通知服务写失败测试：AgentRun completed/failed 持久化一条消息；相同 dedupe key 重试仍为一条。

### 验证清单

- 新测试在未实现时因目标行为缺失而失败，而不是因 import、fixture 或环境配置失败。
- 真实 V2 响应测试明确断言 JSON key 不含 `run_id`、`conversation_id`。
- 保存失败测试输出作为 Phase 1～5 的回归基线。

### 反模式约束

- 不再用 snake_case Mock 迎合当前组件 Bug。
- 不用 sleep 驱动脆弱的异步测试；使用 fake timers、可控 promise 或事件 fixture。
- 不修改爬虫相关测试以凑全量通过。
- 不在测试中复制一套与真实 Pydantic Serializer 无关的手写响应。

### 检查点

提交一份测试清单：每个失败测试对应 Spec 中一个验收条件，评审通过后进入 Phase 1。

## Phase 1：修复职业分析创建、错误和活动任务恢复

### 目标

先消除“后端成功、前端报失败”的 P0 问题，并让服务端业务错误准确到达页面。

### 参考实现

- V2 命名：`jobCollectionWebApi/schemas/v2/common.py`
- 职业 API 边界：`frontend/src/api/career.js`
- 职业页面：`frontend/src/views/CareerAnalysisView.vue`
- 全局异常：`jobCollectionWebApi/main.py`
- Agent 幂等和活动运行准入：`jobCollectionWebApi/api/v1/endpoints/agent_controller.py:submit_message`
- V2 职业服务：`jobCollectionWebApi/services/v2/career_service.py`

### 实施任务

1. 在 `frontend/src/api/career.js` 增加小型响应 Adapter，向组件只返回 camelCase 领域对象。
2. 修改 `CareerAnalysisView.vue`，只读取 `runId`、`conversationId`、`createdAt` 等 V2 camelCase 字段。
3. 新建共享错误工具，例如 `frontend/src/utils/apiError.js`，实现 Spec 的错误优先级和 `retryable`。
4. 首页与职业分析都使用共享错误工具，删除局部 `detail`-only 读取。
5. 对齐前后端错误码，至少覆盖 `AGENT_DEADLINE_EXCEEDED`、`AGENT_LLM_TIMEOUT`、`AGENT_EVIDENCE_UNAVAILABLE`、`AGENT_DISPATCH_FAILED`。
6. V2 职业服务遇到不同幂等键的活动 run 时返回 `AGENT_ACTIVE_RUN_EXISTS` 及现有 run 元数据。
7. 页面把该 409 处理为“恢复现有任务”，保存 run 并启动追踪，不进入失败态。
8. 补 `waiting_user`、`cancelled` 的明确状态处理。
9. 临时保留轮询时，将 `setInterval(async ...)` 改为串行递归 `setTimeout`，并在卸载时 abort/clear。

### 验证清单

- `CareerAnalysisView.test.js` 使用 camelCase Mock 后通过。
- API 契约测试通过。
- 202 创建成功不会显示错误。
- 409 active run 会恢复同一个 run。
- 后端 `msg` 原文可在页面看到；内部异常不泄漏。
- fake timers 证明 3 秒以上请求不会产生第二个并发轮询。
- 组件卸载后没有新的 HTTP 请求。

### 反模式约束

- 不在每个 Vue 页面各写一套错误提取逻辑。
- 不在组件中长期保留 `runId || run_id`。
- 不把所有 409 都视为可恢复，必须检查稳定错误码和完整 run data。
- 不通过“把错误提示改得更宽泛”掩盖契约错误。

### 检查点

手工走通：首次创建、重复同 key、已有不同 active run、模型超时、数据不足、取消六条路径。

## Phase 2：增加 Agent 正文流事件

### 目标

在不破坏结构化答案和成功后扣费语义的前提下，提供可回放的正文 delta。

### 参考实现

- 事件枚举/Schema：`jobCollectionWebApi/agent/events.py`
- 发布器与事件存储：`jobCollectionWebApi/agent/event_store.py`
- SSE 回放：`jobCollectionWebApi/agent/sse.py`
- Runtime 成功路径：`jobCollectionWebApi/agent/runtime.py:execute`、`_save_answer`
- 结构化模型调用：`jobCollectionWebApi/services/llm_client.py:complete_structured`
- Runtime 测试：`tests/test_agent_runtime.py`
- SSE 测试：`tests/test_agent_events.py`

### 实施任务

1. 在 `AgentEventType` 增加 `MESSAGE_STARTED`、`MESSAGE_DELTA`。
2. 新建纯函数 Markdown chunker，按段落/句子/列表项切分并保证 Unicode 安全。
3. 为 chunker 写中英文、emoji、超长段落、Markdown 列表和空答案测试。
4. Runtime 在结构化 `AgentAnswer` 验证成功后生成一次最终 Markdown。
5. 发布 `message_started`，随后按严格 index 发布 delta。
6. delta 发布结束后保存最终消息、完成 run 和计费，再发布 `message_completed` 与 `run_completed`。
7. `message_completed` 携带权威 `content`、结构化 `result`、`deltaCount`。
8. capability 改为 `supports_message_delta=true`，并增加 `message_stream_mode`。
9. Redis 发布失败时记录指标，但继续完成数据库成功路径；最终 HTTP 快照可恢复。
10. 确保取消/租约丢失/超时在终态后不再产生 delta。

### 事务与计费顺序评审

实施前必须明确并用测试固定：

```text
LLM 成功 + Schema 校验
→ 准备最终 Markdown
→ 发布展示 delta（非事实提交）
→ 单一数据库成功事务：assistant message + completed run + billing ledger
→ message_completed/run_completed
→ 事务后持久通知（可重试、幂等）
```

若现有账本无法与消息/run 保持同一事务，应采用唯一业务引用 + 可恢复补偿，不得用 SSE 成功与否决定扣费。

### 验证清单

- 单元测试断言事件顺序和 index 连续。
- 重放同一 stream 不产生重复业务正文。
- Redis publish 抛错时 run 仍能按业务结果正确 completed/failed。
- failed/cancelled/timeout 均无扣费，无 `message_completed`。
- completed 重试不重复保存消息、不重复扣费。
- 既有 Agent API 和 SSE 测试全部通过。

### 反模式约束

- 不在本阶段替换 `complete_structured()` 为未经验证的 token stream。
- 不把每个 token 写 PostgreSQL。
- 不在打开数据库事务时人为 sleep 展示打字效果。
- 不在 `run_completed` 之后发布 delta。
- 不因 Redis/SSE 故障把有效 AI 结果标为失败。

### 检查点

用固定回答运行一次事件录制，输出完整 event sequence、最终拼接正文和数据库消息三者的一致性证据。

## Phase 3：首页与职业分析接入共享 SSE 追踪器

### 目标

移除两套页面级轮询主路径，提供“正在回答”占位、阶段反馈、正文流和断线降级。

### 参考实现

- SSE 连接：`frontend/src/utils/sseClient.js`
- 事件处理、去重、重连：`frontend/src/stores/agent.js`
- 首页当前轮询：`frontend/src/views/HomeView.vue:pollMarketRun`
- 职业分析当前轮询：`frontend/src/views/CareerAnalysisView.vue:startRunPolling`
- Agent Store 测试：`frontend/src/stores/agent.test.js`

### 实施任务

1. 抽取共享 composable/store，例如 `useAgentRunStream`，不要把 Home 和 Career 硬耦合到整个 Agent Workspace Store。
2. 共享层负责：单连接、事件去重、游标、状态机、delta buffer、重连、降级轮询和清理。
3. `stores/agent.js` 改为复用共享层，避免第三套事件解析。
4. 首页提交时立即插入本地 user message 和 assistant placeholder。
5. 收到 delta 后按帧批处理并追加；completed 后用服务端完整正文校准并加载历史。
6. 职业报告和职业顾问问答接入相同追踪器。
7. 职业报告 completed 后刷新 overview/latest report；failed 时保留旧成功报告。
8. 实现智能自动滚动：用户在底部时跟随，离开底部时显示新内容提示。
9. SSE 连续失败后显示降级提示并串行轮询；恢复终态后停止所有连接和 timer。
10. 使用现有或受控 Markdown renderer，增加 XSS 用例。

### 验证清单

- 页面提交后不等 POST 后续轮询即可看到占位气泡。
- started/delta/completed 组件测试通过。
- 乱序或重复事件不会重复正文。
- `message_completed.content` 能修正遗漏 delta。
- Abort 后无状态更新、无控制台 unhandled rejection。
- 每个 run 最多一个 SSE；降级时最多一个轮询请求。
- 100+ delta 下更新批次受控，输入框和滚动保持流畅。

### 反模式约束

- 不在 `HomeView.vue`、`CareerAnalysisView.vue` 分别复制 SSE parser。
- 不对每个 delta 直接触发昂贵 Markdown 全量渲染。
- 不强制滚动打断用户阅读历史消息。
- 不用 `v-html` 直接渲染未清洗模型内容。
- 不让轮询和 SSE 同时作为活跃主通道。

### 检查点

录屏或浏览器验收：首页与职业顾问各完成一次正常流、一次断线恢复、一次后端失败。

## Phase 4：统一通知领域服务与数据库模型

### 目标

让简历解析和职业分析终态都生成可恢复、可跳转、去重的持久消息。

### 参考实现

- 当前模型：`common/databases/models/message.py`
- 当前 Schema：`jobCollectionWebApi/schemas/message_schema.py`
- 当前消息 CRUD/API：通过 `rg "MessageCreate|messages" jobCollectionWebApi` 精确定位后完整阅读
- 旧通知任务：`jobCollectionWebApi/tasks/notification_tasks.py`
- 简历终态：`jobCollectionWebApi/tasks/resume_parser.py`
- Agent 终态：`jobCollectionWebApi/agent/runtime.py`、`jobCollectionWebApi/tasks/agent_tasks.py`
- 迁移模式：项目现有 Alembic revisions（执行时选择最近、非爬虫的通用 migration 作为格式参考）

### 实施任务

1. 创建 Alembic migration，新增 `category`、`status`、`action_type`、`action_data`、`source_type`、`source_id`、`dedupe_key`。
2. 历史行允许 nullable；为 `dedupe_key` 建唯一约束/唯一索引，为接收者+分类+时间建查询索引。
3. 更新 ORM 和 Pydantic Schema；所有 Snowflake/source ID 对前端序列化为字符串。
4. 创建 `NotificationService`，只接受结构化字段，不接受调用方拼装的任意 JSON 文本。
5. 实现数据库幂等写入，事务提交后发布 `new_message`。
6. 简历 completed/failed 改用统一服务。
7. Career `AgentRun` completed/failed/cancelled 接入统一服务。
8. 旧 AiTask 在仍被使用的路径上通过适配器接入统一服务，保留兼容行为。
9. 增加通知持久化、去重、WS 发布失败、数据库失败和任务重试测试。
10. 增加 migration upgrade/downgrade 结构测试；生产部署只执行 upgrade，downgrade 仅供测试验证。

### 验证清单

- 空库 upgrade 成功；现有数据 upgrade 后仍可查询。
- 相同 source/status 重试只产生一条消息。
- WS 不可用时消息仍写库，之后刷新可见。
- 数据库写入失败时不会发出幽灵 WS 通知。
- 简历与职业分析完成/失败的 title、category、status、action 正确。
- 敏感简历正文、token 不进入 `action_data`。

### 反模式约束

- 不删除旧列或强制历史行一次性补全。
- 不继续依赖被注释的 `action_param`。
- 不在 Celery task 中各写一套 `Message(...)`。
- 不先发 WS 再写数据库。
- 不使用普通“先查再插”作为唯一去重手段，必须有数据库唯一约束兜底。

### 检查点

在测试数据库执行两次相同 completed 回调，展示只有一条消息、一次有效未读计数的证据。

## Phase 5：消息中心 V2 UI 与实时一致性

### 目标

修复“空白/不可见”体验，支持分类、状态、正确跳转、错误重试和实时更新。

### 参考实现

- 当前页面：`frontend/src/views/MessageCenter.vue`
- 全站布局 WS：`frontend/src/layout/BasicLayout.vue`
- 任务 Store：`frontend/src/stores/aiTask.js`
- 路由：`frontend/src/router/**` 中的 `career-analysis`、`my-resume` 实际命名
- 当前 V2 UI 视觉基线：`frontend/src/views/CareerAnalysisView.vue`、个人中心相关页面

### 实施任务

1. API 增加分页和分类/未读筛选，返回统一 V2 message view。
2. 页面状态拆为 `loading`、`loaded`、`empty`、`error`、`loadingMore`。
3. 重做消息列表卡片：类型、状态、时间、摘要、已读和动作按钮。
4. 增加全部/未读/简历/职业分析筛选。
5. 修复动作路由：职业分析统一 `/career-analysis`，简历统一当前真实简历页。
6. route 与 query/params 必须经过白名单 Adapter。
7. 收到 `new_message` 后由共享通知 Store 重新拉取未读数和第一页，并按 ID 去重。
8. 顶部布局不再无条件 `unreadCount += 1`；以服务端计数校准。
9. 增加键盘访问、焦点态、ARIA label、移动端布局和长文本截断/展开。
10. 为所有页面状态和点击动作补组件测试。

### 验证清单

- API 失败显示错误和重试，不显示“暂无消息”。
- 简历/职业 completed 和 failed 均可见。
- 点击职业通知只到 `/career-analysis`。
- WS 重复事件、多标签页模拟不会重复插入或重复增加未读数。
- 标记已读后页面与 Header 数字一致。
- 320px、768px、1440px 三档视口无内容溢出，键盘可操作。

### 反模式约束

- 不用颜色作为唯一状态表达。
- 不信任后端任意 route 做开放跳转。
- 不把接口错误当空列表。
- 不一次加载全部历史消息。
- 不同时在 Layout 和 MessageCenter 各自维护不可校准的未读局部计数。

### 检查点

用四类实际测试消息（简历成功/失败、职业成功/失败）完成页面和跳转验收。

## Phase 6：全链路验证、性能与部署配置验收

### 目标

证明功能、错误、断线、计费和部署代理配置均符合上线标准。

### 参考实现

- 前端脚本：`frontend/package.json`
- 后端测试配置：`pytest.ini` / `pyproject.toml`（执行时确认实际入口）
- Nginx：`deploy/nginx/job.conf`、`deploy/nginx/container.conf`
- Supervisor：`deploy/supervisor/jobcollection.conf`
- Agent API 契约：`tests/test_agent_api_contract.py`
- Agent events/runtime：`tests/test_agent_events.py`、`tests/test_agent_runtime.py`
- V2 Career：`tests/test_v2_career_profile.py`

### 实施任务

1. 运行本任务相关前后端测试，再运行不包含爬虫执行的前后端全量测试集合。
2. 运行 lint、type/build；确认生产构建无 warning escalation 和 chunk 错误。
3. 使用真实浏览器和测试账户跑验收矩阵。
4. 用可控代理/DevTools 中断 SSE，验证 `Last-Event-ID` 恢复和轮询降级。
5. 检查 Nginx 对 `/api/v1/agent/runs/*/events`：禁用 buffering/compression 转换、read timeout 足够、立即 flush header。
6. 检查 Supervisor API/Celery realtime worker 配置与日志，确保 Agent run 能实际消费。
7. 核对 5 种账本场景：成功、LLM timeout、deadline、cancel、同 key 重试。
8. 核对通知 4 种场景：简历成功/失败、职业成功/失败。
9. 对 100 次模拟 delta 做前端性能 profile，检查长任务内存、timer 和连接泄漏。
10. 输出验收记录、剩余风险和上线/回滚步骤；未经用户授权不部署。

### 端到端验收矩阵

| 场景 | 页面结果 | 后端结果 | 扣费 | 消息中心 |
| --- | --- | --- | --- | --- |
| 首页正常回答 | 占位→阶段→delta→完整答案 | completed | 1 次 | 默认无全站通知 |
| 首页 SSE 断线 | 提示重连，最终恢复 | completed | 1 次 | 默认无 |
| 职业报告正常 | 进度→报告刷新 | completed | 1 次 | 1 条 completed |
| 已有职业任务 | 恢复现有 run | 无新 run | 无重复 | 终态仅 1 条 |
| LLM timeout | 可读错误，可重试 | failed | 0 | 1 条 failed |
| 用户取消 | 已取消 | cancelled | 0 | 1 条 cancelled（若产品保留） |
| 简历解析成功 | 资料可查看/确认 | completed | 按现有规则 | 1 条 completed |
| 简历解析失败 | 可读错误，可重试 | failed | 0 | 1 条 failed |

### 验证清单

- Spec 第 15 节全部验收项有测试或人工证据。
- `git diff --check` 通过。
- 没有修改 `jobCollection` 爬虫代码。
- 未提交改动没有被覆盖或混入任务提交。
- Nginx 实际生效配置与仓库配置一致。
- 前端无重复请求、重复消息、明显卡顿和控制台错误。

### 反模式约束

- 不只用本地开发服务器宣称生产 SSE 可用。
- 不只检查 HTTP 200；必须验证事件时序和前端逐步渲染。
- 不用模拟成功替代 timeout/cancel/断线验证。
- 不在未核对 migration、worker 和 Nginx 前直接上线。
- 不因非本任务的爬虫测试失败而修改爬虫实现。

## 建议提交拆分（实施时）

若用户后续授权提交，建议每个提交都可独立测试和回滚：

1. `test: lock career v2 and agent stream contracts`
2. `fix: normalize career responses and api errors`
3. `feat: publish replayable agent message deltas`
4. `feat: stream agent answers in home and career ui`
5. `feat: persist unified task notifications`
6. `feat: rebuild message center task status ui`
7. `test: add end-to-end realtime and notification coverage`

不得将数据库 migration、Agent Runtime、两个大页面和部署配置压成一个不可审查的大提交。

## 完成定义

只有同时满足以下条件，任务才算完成：

- 所有验收项通过；
- 真实 V2 契约与前端一致；
- 首页和职业顾问能看到逐步回答；
- 职业分析不会误报任务创建失败；
- 后端可读错误准确展示；
- 简历与职业分析终态在消息中心可见、可跳转；
- failed/cancelled/timeout 不扣费；
- SSE 断线可恢复且不会重复正文；
- 生产代理配置支持 SSE；
- 未触碰爬虫实现。
