# Batch 3：工具契约和市场工具适配

## 目标

将现有搜索、统计、专业、城市和行业分析能力包装为受控只读工具，向 Agent 输出统一的数据契约。

## 依赖

- Batch 0 已冻结工具契约。
- Batch 1/2 已具备用户上下文和 Agent 运行边界。

## 新增文件

```text
jobCollectionWebApi/agent/tools/base.py
jobCollectionWebApi/agent/tools/registry.py
jobCollectionWebApi/agent/tools/schemas.py
jobCollectionWebApi/agent/tools/normalizers.py
jobCollectionWebApi/agent/tools/resolvers.py
jobCollectionWebApi/agent/tools/job_tools.py
jobCollectionWebApi/agent/tools/analysis_tools.py
```

## 工具上线顺序

1. `search_jobs`
2. `get_market_overview`
3. `get_skill_demand`
4. `get_major_directions`
5. `compare_cities`
6. `compare_industries`

## 现有代码复用

```text
services/search_service.py
services/analysis_service.py
services/comparison_analysis_service.py
crud/job.py
crud/city.py
crud/industry.py
crud/major.py
```

## 适配器必须解决

- 城市名称到 code 的解析和未知城市提示。
- 行业名称、父行业和子行业的语义。
- 薪资单位统一。
- ES 与 PostgreSQL 结果统一。
- 搜索 industry、skills 过滤缺失问题。
- 市场分析 keyword、industry、city 过滤缺失问题。
- 技能统计的 count、ratio、sample_size 和稳定排序。
- 城市/行业比较从双对象转换为列表结果。
- 专业方向标注数据来源和验证状态。

## 统一输出

所有工具边界统一返回：

```json
{
  "ok": true,
  "data": {},
  "sample_size": 0,
  "filters": {},
  "data_as_of": null,
  "source": "elasticsearch",
  "warnings": []
}
```

ES 和 PostgreSQL 都失败时返回 `ok=false`，不能抛出内部异常给 Agent 或用户。

## 工具安全规则

- 输入全部使用 Pydantic。
- 只允许注册表中的工具。
- 模型不能传入 SQL、ES DSL 或数据库字段名。
- 限制关键词、城市、行业、技能数量和 `limit <= 50`。
- 工具层不执行用户数据写入和副作用。

## 验收标准

- 六个工具均能独立调用。
- 每个工具有成功、空数据、ES 降级和双失败测试。
- 结果包含来源、样本量、过滤条件、数据时间和警告。
- 结果格式不依赖旧 Controller 的响应结构。
