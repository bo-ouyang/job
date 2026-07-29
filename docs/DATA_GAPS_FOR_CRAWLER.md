# 前端 V2 数据缺口清单

> 目标：记录数据库当前无法可靠提供、需要爬虫或离线数据任务补齐的字段。为保证 V2 原型可完整展示，后端会对缺失维度提供确定性的测试数据，但不会写入生产业务表；接口通过 `dataStatus.missingDimensions` 和 `dataStatus.syntheticDimensions` 同时暴露真实缺口与测试数据范围。

| Key | 页面模块 | 缺少的数据 | 当前测试展示字段 | 建议来源 | 更新频率 | 优先级 |
|---|---|---|---|---|---|---|
| `market.monthly_job_trend` | 行业趋势 | 月度有效岗位量、同比、环比 | `heroSignals`、`trend`、`signals` | 职位发布时间与每日快照 | 每日 | P0 |
| `market.salary_percentiles` | 薪资分布 | 分维度 P25/P50/P75 与样本量 | `citySalaries`、`salarySummary` | 标准化月薪 + 每日聚合 | 每日 | P0 |
| `market.normalized_skill_frequency` | 热门技能 | 技能别名、标准技能码、历史频率 | 仅在原始技能也为空时回退 `skills` | 职位描述、要求、AI 技能标签 | 每日 | P0 |
| `market.city_competition` | 城市对比 | 候选人才供给量、竞争比 | `cityMatrix` | 外部人才供给或站内画像汇总 | 每周 | P1 |
| `market.talent_shortage_index` | 行业机会榜 | 行业人才供给、缺口指数 | `rankings` | 岗位需求 + 人才供给 | 每周 | P1 |
| `market.talent_structure` | 人才结构 | 学历、经验标准化占比 | `talentStructure` | 职位学历与经验字段聚合 | 每日 | P1 |
| `market.filter_taxonomy` | 首页筛选 | 城市、行业稳定编码与名称 | `filters.cities`、`filters.industries` | 基础字典表与职位字段 | 每日 | P1 |
| `market.source_coverage` | 数据质量 | 来源覆盖率、失败率、新鲜度 | 无 | 爬虫运行日志与失败表 | 每小时 | P1 |

## 职业分析数据缺口

| Key | 负责模块 | 缺少的数据 | 当前测试展示字段 | 补齐方式 | 优先级 |
|---|---|---|---|---|---|
| `career.agent_report` | Agent | 基于真实用户资料与市场证据的职业方向报告 | `directions`、`evidence` | 用户主动生成 Agent 报告 | P0 |
| `career.city_comparison` | 市场数据 | 目标方向分城市岗位量、薪资、增长、竞争度 | `cities` | 市场快照 + 城市竞争数据 | P1 |
| `career.skill_gap` | Agent | 用户技能与目标岗位要求差距 | `skills` | 已确认技能 + 标准岗位技能 | P0 |
| `career.action_plan` | Agent | 30/60/90 天行动计划 | `plan` | Agent 根据真实技能差距生成 | P1 |

职业分析回退只替换缺失的分析结果，用户姓名、学校、专业、课程、技能等个人资料始终读取真实数据库，不会使用或写入测试身份资料。

## 测试数据使用规则

1. 测试数据集中维护在 `jobCollectionWebApi/services/v2/market_test_data.py`，禁止写入 `jobs`、统计快照或其他生产业务表。
2. 数据库已有的职位总量、行业、技能和薪资分布始终优先；仅当对应展示维度为空时才使用测试值。
3. 混合响应的 `dataStatus.source` 为 `mixed`，完全依赖测试展示数据时为 `synthetic`。
4. 前端必须显示测试数据提示，不能将测试增长率、薪资或人才缺口描述为真实统计结果。
5. 爬虫或离线任务补齐维度后，从 `syntheticDimensions` 移除对应 key，再删除该字段的测试回退。

## 爬虫交付约束

1. 所有历史统计必须保留 `snapshot_date` 或 `snapshot_month`，不能只覆盖当前值。
2. 薪资统一换算为人民币月薪，并保留原始薪资文本、单位和换算规则版本。
3. 城市、行业、学校、专业和技能必须使用稳定编码；原始名称单独保留。
4. 每次采集保留 `source_site`、`source_url`、`crawled_at` 和解析版本。
5. 数据任务完成后，将对应缺口状态从 `missing` 更新为 `collecting`，达到覆盖率门槛后改为 `available`。
