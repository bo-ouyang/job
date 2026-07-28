# Batch 6：前端 Agent 工作台

## 原型实现约束

本 Batch 以 `frontend/` 目录下的原型文档和两张原型图为验收基线。Agent 工作台不能实现为单栏聊天页，必须同时承载对话、用户背景、资料、职业方向、成长路线、技能差距、岗位推荐和本周任务。

## 目标

提供统一的 `/agent` 入口，用户只需自然语言描述情况，不需要先选择专业分析、职业罗盘等功能。

## 依赖

- Batch 2 API 契约已稳定。
- Batch 5 SSE 事件协议已稳定。
- Batch 7 的前端测试工具可以在本批同步引入。

## 新增文件

```text
frontend/src/api/agent.js
frontend/src/stores/agent.js
frontend/src/utils/sseClient.js
frontend/src/views/AgentWorkspace.vue
frontend/src/views/AgentConversation.vue
frontend/src/components/agent/AgentConversation.vue
frontend/src/components/agent/AgentRadarChart.vue
frontend/src/components/agent/AgentIcon.vue
```

## 修改文件

```text
frontend/src/router/index.js
frontend/src/layout/BasicLayout.vue
frontend/src/assets/main.css
frontend/package.json
```

## API 模块

实现：

```text
createConversation
listConversations
getConversation
sendMessage
getRun
cancelRun
```

SSE 解析放入 `sseClient.js`，不要塞入 Axios `request.js`。

## Pinia store

状态：

```text
conversations
activeConversation
messages
activeRun
runEvents
careerProfileDraft
connectionState
lastEventSequence
reconnectAttempt
error
```

必须保证：

- 一个运行只有一个活动流。
- 事件按 ID/sequence 去重。
- 当前后端没有真实 `message_delta`，使用 `message_completed` 定稿并在终态后重载 REST 会话快照。
- 刷新后先加载会话和运行，再恢复流或查询终态。
- 断线不重复发送消息。
- 旧 `aiTask.js` 继续处理旧 Celery AI。

## 已落实的数据源模式

```text
mock   全部使用本地演示数据
hybrid 对话、运行和 SSE 使用真实 API，规划卡片使用明确标识的演示数据
api    对话、运行和 SSE 使用真实 API，后端尚未提供的规划卡片仍标识为演示数据
```

开发环境默认 `hybrid`，生产环境配置为 `api`。在结构化规划、任务、资料和推荐接口上线前，前端不会把这些卡片标记成实时数据。

## 页面布局

桌面：

```text
[会话列表] [消息和运行时间线] [职业画像/证据/行动]
```

移动端：会话列表使用抽屉，右侧信息使用折叠区或底部面板，输入框固定在可视区域底部。

## 工作项

- [x] 增加 `/agent` 和 `/agent/:conversationId` 路由。
- [x] 受登录和 Agent feature flag 保护。
- [x] 实现会话加载、自动创建和自然语言输入。
- [x] 实现工具状态、追问、完整答案和终态展示。
- [x] 实现取消、Last-Event-ID 重连和刷新恢复。
- [x] 保证移动端核心布局可用。
- [x] 保持首页和旧 AI 页面可访问。
- [ ] 增加独立的历史会话列表/抽屉，该项在结构化规划接口后继续完善。
- [ ] 增加真实 Token 级 `message_delta`，依赖后端流式 LLM 能力。

## 验收标准

- 用户不需要选择旧 AI 功能即可开始职业分析。
- 能区分用户消息、回答、工具状态、追问和错误。
- 刷新页面可以恢复当前会话和运行。
- SSE 断线不会产生第二个 AgentRun。
- 桌面和移动端核心流程可用。
