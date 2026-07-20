# 职业规划 Agent 重构文档索引

## 总体设计

```text
职业规划Agent重构总路线图.md
职业规划Agent一期MVP产品与技术方案.md
职业规划Agent工具契约与数据模型.md
职业规划Agent实施任务与验收标准.md
职业规划Agent详细实施计划.md
```

## 目录规划

```text
restructure/
├── README.md                         文档入口
├── foundation/                       设计冻结、基础约束
├── backend/                          数据模型、API、工具、Runtime
├── realtime/                         Redis Streams、SSE、实时事件
├── frontend/                         UI、交互、组件、前端实施
├── quality/                          测试、监控、部署验证
└── release/                          灰度发布、兼容、旧功能下线
```

目录规则：

- 总体设计和跨模块计划放在 `restructure/` 根目录。
- 只属于后端的数据模型、API、工具和 Runtime 放入 `backend/`。
- 跨后端与前端的事件协议和流式基础设施放入 `realtime/`。
- UI、交互、路由、组件和前端状态放入 `frontend/`。
- 测试、指标、环境和代理验证放入 `quality/`。
- 灰度、回滚和旧功能迁移放入 `release/`。
- 新增文档必须选择明确归属，不在根目录继续堆积 Batch 文档。

## Batch 文档

- [Batch 0：设计冻结和测试基线](foundation/Batch%200%20设计冻结和测试基线.md)
- [Batch 1：数据模型迁移和安全 CRUD](backend/Batch%201%20数据模型迁移和安全CRUD.md)
- [Batch 2：会话 API 和运行派发](backend/Batch%202%20会话API和运行派发.md)
- [Batch 3：工具契约和市场工具适配](backend/Batch%203%20工具契约和市场工具适配.md)
- [Batch 4：Agent Runtime 和状态机](backend/Batch%204%20Agent%20Runtime和状态机.md)
- [Batch 5：Redis Streams 和 SSE 实时事件](realtime/Batch%205%20Redis%20Streams和SSE实时事件.md)
- [Batch 6：前端 Agent 工作台](frontend/Batch%206%20前端Agent工作台.md)
- [Batch 7：测试、监控和部署验证](quality/Batch%207%20测试监控和部署验证.md)
- [Batch 8：灰度发布和旧功能共存](release/Batch%208%20灰度发布和旧功能共存.md)

## 前端文档

- [前端信息架构与视觉方向](frontend/01-产品信息架构与视觉方向.md)
- [Agent 工作台交互与事件状态](frontend/02-Agent工作台交互与事件状态.md)
- [前端组件、状态与路由设计](frontend/03-组件状态与路由设计.md)
- [前端实施计划与验收](frontend/04-前端实施计划与验收.md)
