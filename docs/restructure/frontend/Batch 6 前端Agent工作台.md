# Batch 6：前端 Agent 工作台

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
frontend/src/views/AgentWorkspace.vue
frontend/src/views/AgentConversation.vue
frontend/src/components/agent/AgentShell.vue
frontend/src/components/agent/ConversationList.vue
frontend/src/components/agent/MessageTimeline.vue
frontend/src/components/agent/MessageComposer.vue
frontend/src/components/agent/RunStatusPanel.vue
frontend/src/components/agent/ToolExecutionCard.vue
frontend/src/components/agent/CareerProfileCard.vue
frontend/src/components/agent/DirectionCard.vue
frontend/src/components/agent/ActionPlanCard.vue
frontend/src/components/agent/ClarificationCard.vue
frontend/src/components/agent/AgentErrorState.vue
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
- `message_delta` 增量拼接，`message_completed` 定稿。
- 刷新后先加载会话和运行，再恢复流或查询终态。
- 断线不重复发送消息。
- 旧 `aiTask.js` 继续处理旧 Celery AI。

## 页面布局

桌面：

```text
[会话列表] [消息和运行时间线] [职业画像/证据/行动]
```

移动端：会话列表使用抽屉，右侧信息使用折叠区或底部面板，输入框固定在可视区域底部。

## 工作项

- [ ] 增加 `/agent` 和 `/agent/:conversationId` 路由。
- [ ] 受登录和 Agent feature flag 保护。
- [ ] 实现会话列表和自然语言输入。
- [ ] 实现工具状态、追问、增量答案和终态展示。
- [ ] 实现取消、重连和刷新恢复。
- [ ] 保证移动端不出现横向溢出和输入框遮挡。
- [ ] 保持首页和旧 AI 页面可访问。

## 验收标准

- 用户不需要选择旧 AI 功能即可开始职业分析。
- 能区分用户消息、回答、工具状态、追问和错误。
- 刷新页面可以恢复当前会话和运行。
- SSE 断线不会产生第二个 AgentRun。
- 桌面和移动端核心流程可用。
