# 实施交接提示

## 系统 1：清除废弃采集路径

```text
/make-plan 删除 jobCollection 的 legacy GUI/Mitm/Redis、boss_detail_click_drission、失效学校 MySQL Spider 与生成物。依据 PATHFINDER-2026-08-05/01-flowcharts/legacy-and-experimental.md 和 school.md。重写所有仓内引用并更新文档。禁止为废弃路径增加 feature flag、兼容层、registry 或新抽象。
```

## 系统 2：统一 BOSS 解析与详情写入

```text
/make-plan 建立 jobCollection/jobCollection/boss/parsers.py 作为 BOSS 列表 payload、BossJobItem 映射、详情描述解析的单一入口；让 boss_list_drission 与 boss_detail_drission 调用它。让详情 Spider 只产出 BossJobDetailItem，由 boss_pipeline.py:121-180 唯一写库和派发 ES。依据 active-boss.md、boss-detail.md 和 02-duplication-report.md。禁止通用 repository、factory 或双写路径。
```

## 系统 3：统一安全代理支持

```text
/make-plan 将 simple_script/proxy_manager.py 的硬编码 KDL 凭据移至环境变量，并把认证代理扩展生成提取为两个现役 Spider 共用的小函数。删除已跟踪的动态扩展、Cookie/账户/截图数据，提供脱敏 accounts.example.json 并补 .gitignore。禁止默认 secret、明文 fallback 和额外代理真源。
```

## 系统 4：修复现役状态机

```text
/make-plan 修复 boss_list_drission 完成后重复把指定任务改回 processing、空 payload 判成功、页码不推进和任务 done 早于持久化的问题；修复 boss_detail_drission 的 major_name 断点与 is_crawl 失败状态。依据 active-boss.md 和 boss-detail.md。优先删除错误分支和使用现有状态字段，禁止新增状态框架或 feature flag。
```
