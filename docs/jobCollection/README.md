# jobCollection 爬虫

`jobCollection` 当前只保留两条 BOSS 采集链路，均基于 Scrapy + DrissionPage：

- `boss_list_drission`：领取 `boss_crawl_task` 中的列表任务，抓取职位列表并通过 Pipeline 写入 PostgreSQL。
- `boss_detail_drission`：领取 `job` 表中尚未补全的职位，抓取详情描述并通过同一个 Pipeline 更新 PostgreSQL；事务提交后再派发 Elasticsearch 同步。

历史 Playwright/Mitmproxy/GUI 桥接、旧版 Spider、学校 MySQL 爬虫和本地 URL 生成脚本已经删除，不再是可用入口。

## 现役架构

```text
管理后台
  -> CrawlerService
  -> scrapy crawl boss_list_drission -a task_id=... -a task_url=...
  -> BOSS 列表接口
  -> BossJobItem
  -> Redis 去重
  -> BossJobPipeline
  -> PostgreSQL

独立详情 worker
  -> scrapy crawl boss_detail_drission
  -> 原子领取 job.is_crawl=0
  -> BOSS 详情页
  -> BossJobDetailItem
  -> BossJobPipeline
  -> PostgreSQL（提交后再同步 Elasticsearch）
```

公共解析逻辑位于 `jobCollection/jobCollection/boss/parsers.py`，代理池和认证代理扩展位于 `jobCollection/jobCollection/boss/proxy.py`。Spider 不再各自维护字段映射、详情落库或代理凭据。

## 配置

### 账户

列表爬虫需要可登录 BOSS 的账户配置。复制：

```powershell
Copy-Item jobCollection/jobCollection/simple_script/accounts.example.json `
  jobCollection/jobCollection/simple_script/accounts.json
```

然后按运行环境填写本地 `accounts.json`。该文件、Cookie、浏览器 profile 和登录截图都属于运行时敏感数据，已被 Git 忽略，禁止提交。

也可以使用以下方式覆盖账户来源：

- `BOSS_LIST_ACCOUNTS`：账户数组的 JSON 字符串。
- `BOSS_LIST_ACCOUNTS_FILE`：账户 JSON 文件路径。
- Spider 参数 `accounts_json` / `accounts_file`：优先级高于环境变量。

### 代理

代理配置只从环境变量读取：

- `BOSS_PROXY_API_URL`：代理供应商 API；留空时允许直连。
- `BOSS_PROXY_USERNAME`：认证代理用户名。
- `BOSS_PROXY_PASSWORD`：认证代理密码。
- `BOSS_PROXY_MIN_POOL_SIZE`：本地池低水位，默认 `1`。

认证代理所需的 Chromium 扩展在运行时写入唯一临时目录，并在浏览器重建或 Spider 关闭时清理。不要在代码或仓库文件中保存代理凭据。

数据库、Redis 和 Elasticsearch 配置见根目录 `.env.example`。运行时需要 PostgreSQL；Redis 去重与 Elasticsearch 是否启用由 Scrapy/应用配置决定。

## 运行

在仓库根目录安装依赖后，进入 Scrapy 项目目录：

```powershell
Set-Location jobCollection
scrapy list
```

应只看到：

```text
boss_detail_drission
boss_list_drission
```

列表任务通常由管理后台调用 `CrawlerService.run_crawler_task(task_id)` 启动。手动运行指定任务：

```powershell
python -m scrapy crawl boss_list_drission `
  -a task_id=123 `
  -a task_url="https://www.zhipin.com/web/geek/jobs?city=101010100"
```

`task_id` 必须存在且状态为 `pending`。不传指定任务参数时，Spider 会从数据库原子领取待处理任务。

启动详情 worker：

```powershell
python -m scrapy crawl boss_detail_drission
```

## 状态语义

列表任务 `boss_crawl_task.status`：

- `pending`：等待领取，可由调度服务启动。
- `processing`：已被 Spider 原子领取并正在处理。
- `paused` / `stopped`：后台请求暂停或停止；运行进程会结束并清理 PID。
- `done`：页面抓取结束，且本任务产生的 Item 已全部写入成功。
- `error`：登录、抓取或 Pipeline 写入失败，可排查后重置为 `pending`。

详情任务 `job.is_crawl`：

- `0`：等待抓取或失败后已回退，可重试。
- `2`：已被详情 worker 原子领取，正在处理。
- `1`：详情已由 Pipeline 成功写入。

列表和详情 Item 均等待数据库写入完成后才推进状态。Pipeline 写入失败不会被错误标记为成功。

## 验证

```powershell
python -m pytest tests/test_jobcollection_core.py `
  tests/test_jobcollection_architecture.py `
  tests/test_jobcollection_lifecycle.py `
  tests/test_crawler_service.py -q
python -m compileall -q jobCollection jobCollectionWebApi common
Push-Location jobCollection; scrapy list; Pop-Location
```

单元测试不访问真实 BOSS、PostgreSQL、Redis 或 Chromium。发布前仍需在隔离测试环境执行一轮真实链路冒烟测试。
