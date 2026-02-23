# 爬虫计划 (Scrapy Integrated)

## 职位爬虫目标
0.先编写脚本，用来生成爬虫的url 到 spider_boss_crawl_url 表（url = https://www.zhipin.com/web/geek/jobs?city=101010100&industry=100020  ，city和industry 从数据库获取）[已完成]
1.爬虫是使用 Scrapy + Playwright（中间件）来抓取数据。
2.通过 Playwright 注入 cookie + url 进行筛选，每个页面加载不同的 cookie。
3.通过监听网络接口 (`/wapi/zpgeek/search/joblist.json`) 获取数据。
4.每个 url 抓取的数据必须包含日志，日志中必须包含 url，city，industry，页面，是否完成。
5.数据抓取完成后，保存到数据库。

增加多线程爬虫设置：最多打开3个playwright页面

## 执行步骤详情

### 第一步：创建数据模型 (Model Creation) [已完成]
*   文件: `d:/Code/job/common/databases/models/spider_boss_crawl_url.py`

### 第二步：编写 URL 生成脚本 (URL Generation Script) [已完成]
*   文件: `d:/Code/job/jobCollection/generate_urls.py`

### 第三步：配置 Scrapy & Playwright
需要在 `settings.py` 中激活 `scrapy-playwright`。
1.  安装 `scrapy-playwright` (如未安装)。
2.  配置 `DOWNLOAD_HANDLERS` 和 `TWISTED_REACTOR`。
3.  配置并发数 `CONCURRENT_REQUESTS=3`。

### 第四步：编写 Boss Zhipin Spider
创建 Scrapy 爬虫 `d:/Code/job/jobCollection/jobCollection/spiders/boss_spider.py`。
*   **start_requests**:
    *   连接数据库读取 `pending` 任务。
    *   生成 Scrapy Request，meta 中开启 `playwright=True`。
    *   配置 `playwright_page_init_callback` 用于注入 Cookie 和监听 response。
*   **Page Init Callback (parse_page)**:
    *   `page.add_cookies(...)`
    *   `page.on("response", handler)`
    *   `page.goto(url)`
    *   模拟滚动翻页。
*   **Response Handler**:
    *   解析拦截到的 JSON 数据。
    *   Yield Item 到 Pipeline。
*   **Item Pipeline**:
    *   保存 Job 数据到 DB。
    *   更新 `SpiderBossCrawlUrl` 状态。

### 第四步：执行与验证
1.  **运行生成脚本**: `python jobCollection/generate_urls.py`
2.  **检查数据库**: 确认 `spider_boss_crawl_url` 表中有数据。
3.  **运行爬虫**: `python jobCollection/crawler_boss.py`
4.  **监控**: 观察日志输出，确认浏览器行为和数据入库情况。

如果还有补充的  添加到这个文档中