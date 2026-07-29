# API V2 迁移与兼容策略

> 适用代码基线：2026-07-28 工作区

## 1. 迁移目标

新 UI 使用独立的 `/api/v2` 页面契约，旧客户端继续使用 `/api/v1`。V2 不复制底层业务逻辑，而是在独立 Router、Pydantic Schema 和页面聚合 Service 中复用现有 CRUD、市场分析、钱包计费和 Agent Runtime。

基本规则：

- `/api/v1` 完整保留，不修改已有路径和响应含义。
- V2 使用 CamelCase JSON；Snowflake ID 输出为字符串。
- 数据库没有的数据返回空值或空集合，并在 `dataStatus.missingDimensions` 中声明，禁止生成演示数据冒充真实数据。
- Elasticsearch 默认关闭；V2 市场接口优先使用已启用的 ES，否则降级 PostgreSQL。
- 认证、钱包、支付和简历上传暂时继续使用 V1，避免同时迁移高风险基础能力。

## 2. 当前端点映射

| 新 UI 场景 | V2 路径 | 鉴权 | 复用实现/数据源 | V1 状态 |
|---|---|---:|---|---|
| 首页市场大盘 | `GET /api/v2/market/dashboard` | 否 | `MarketDashboardService`、旧统计 CRUD、可选 ES | 保留 |
| 首页 AI 问答 | `POST /api/v2/market/questions` | 是 | Agent 会话、Run、Celery realtime、钱包 | 保留 |
| 数据缺口清单 | `GET /api/v2/meta/data-gaps` | 否 | `data_gap_registry` | 无对应接口 |
| 个人资料 | `GET/PATCH /api/v2/profile` | 是 | User、Resume、CareerProfile | Agent V1 画像接口保留 |
| 专业课程 | `GET/PUT /api/v2/profile/courses` | 是 | `career_profile_courses`、变更记录 | 无对应接口 |
| 专业技能 | `GET/PUT /api/v2/profile/skills` | 是 | `career_profile_skills`、JSONB 兼容快照、变更记录 | Agent V1 JSONB 保留 |
| 职业分析概览 | `GET /api/v2/career-analysis/overview` | 是 | 用户画像、最新 Agent 结构化结果 | 传统分析接口保留 |
| 最新职业报告 | `GET /api/v2/career-analysis/reports/latest` | 是 | 最新 Agent `analysis_result` 消息 | 传统 AI 历史接口保留 |
| 生成职业报告 | `POST /api/v2/career-analysis/reports` | 是 | Agent Runtime、`career_compass` 定价 | 传统职业罗盘保留 |
| 职业追问 | `POST /api/v2/career-analysis/questions` | 是 | Agent Runtime、`career_advice` 定价 | Agent V1 会话接口保留 |
| AI 定价 | `GET /api/v2/ai/pricing` | 否 | Product、`AIAccessService`、后端配置 | 旧 AI 接口保留 |

认证、Token 刷新、钱包、支付、简历文件上传和旧业务页面仍调用 `/api/v1`。

## 3. 前端客户端边界

- `frontend/src/utils/request.js`：V1 客户端，默认根路径 `/api/v1`，继续承载认证、钱包、支付、简历和旧页面。
- `frontend/src/utils/v2Request.js`：V2 客户端，默认根路径 `/api/v2`，承载 market、career、profile 新 UI API。
- 两个客户端共享本地 Access Token 和 V1 Refresh Token 流程；都解包统一响应，并保留 HTTP 402 余额不足事件。

生产环境可通过 `VITE_API_V2_BASE_URL` 覆盖 V2 根路径。

## 4. V2 数据状态

市场和职业分析聚合响应包含：

```json
{
  "dataStatus": {
    "source": "postgresql",
    "degraded": true,
    "updatedAt": "2026-07-28T16:00:00",
    "availableDimensions": ["market.kpis"],
    "missingDimensions": ["market.monthly_job_trend"]
  }
}
```

`source` 表示本次真实来源；`degraded` 表示部分维度不可用，而不是请求整体失败。爬虫负责的数据缺口维护在 `docs/DATA_GAPS_FOR_CRAWLER.md`，状态按 `missing → collecting → available` 更新。

## 5. 职业画像迁移

现有 `career_profiles.education/skills/experience/preferences` JSONB 保留，作为 V1 兼容和聚合快照。V2 新增：

- `career_profile_courses`：课程名称、分类、掌握程度、来源、确认状态和证据。
- `career_profile_skills`：技能名称、熟练度、使用年限、来源、确认状态和证据。
- `career_profile_change_logs`：修改前后快照、冲突数据、来源和审核状态。

课程和技能按 `(profile_id, normalized_name)` 去重。只有 `confirmation_status=confirmed` 的规范化数据进入 Agent 上下文；简历解析出的候选资料可以先保存为 `pending/conflict`，用户确认后再参与分析。

相关迁移：

- `20260728_01_normalize_career_profile_collections`
- `20260728_02_add_agent_run_billing`

## 6. Agent 幂等与计费

- 报告、职业问答和首页问答都强制携带 `Idempotency-Key`。
- V2 在新建会话前按 `user_id + idempotency_key` 查找已有 Run，重试返回原 Run。
- 提交时调用后端定价和钱包服务校验余额，并把功能类型与价格快照写入 `agent_runs`。
- 只有 Agent 成功生成答案时才扣款；订单号固定为 `agent_run:{run_id}`，扣款、答案消息和 Run 终态原子提交，Worker 重试不会重复消费。
- 余额不足保持 HTTP 402 契约；运行失败或取消不扣款。

## 7. V1 废弃策略

当前不发送 Deprecation/Sunset Header，也没有 V1 删除日期。只有同时满足以下条件后才能开始废弃：

1. 所有生产前端和外部客户端完成迁移并完成调用量审计。
2. V2 在生产环境经过完整观察周期，错误率、延迟和 Agent 成功率达标。
3. 钱包、认证和简历等尚留在 V1 的能力已有明确迁移版本。
4. 产品负责人批准下线日期和用户通知方案。

废弃时先增加 `Deprecation: true`、`Sunset` 和替代接口 `Link`，至少保留一个约定迁移周期后再删除代码。
