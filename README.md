# Job Collection & Analysis Platform (招聘数据采集与分析平台)

这是一个基于 **FastAPI** 和 **Scrapy** 的招聘数据采集、分析与可视化平台。支持 Boss 直聘的数据采集、自动投递（模拟）、薪资分析及大屏展示。

## 📂 项目结构

- **`jobCollectionWebApi/`**: 后端 API 服务 (FastAPI)。提供数据接口、用户认证、支付、大屏数据等。
- **`jobCollection/`**: 爬虫子系统 (Scrapy + DrissionPage/PyAutoGUI)。负责采集职位数据、自动化交互。
- **`common/`**: 公共模块。包含数据库模型 (`models`)、工具类等。
- **`vue-admin/`** (假设存在): 前端管理后台 (Vue.js)。

## 🚀 快速开始

### 1. 环境准备

确保已安装：
- Python 3.10+
- PostgreSQL
- Redis
- Chrome 浏览器

### 2. 安装依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

### 3. 配置环境

1.  进入 `jobCollectionWebApi/` 目录。
2.  复制 `.env.example` (需创建) 或直接创建 `.env` 文件。
3.  填入必要的配置信息 (数据库、Redis、密钥等)。

```ini
# .env 示例
POSTGRES_PASSWORD=your_postgres_password
REDIS_PASSWORD=your_redis_password
SECRET_KEY=your_jwt_secret_key
# ... 其他配置
```

### 4. 运行服务

#### 启动后端 API

```bash
cd jobCollectionWebApi
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

访问 API 文档: `http://localhost:8000/docs`

#### 启动爬虫/监控

*需启动 Redis 服务*

1.  **启动爬虫 (Worker)**:
    ```bash
    cd jobCollection
    scrapy crawl boss_monitor
    ```

2.  **启动浏览器控制器 (Controller)**:
    ```bash
    cd jobCollection
    python boss_drission_controller.py
    ```

## 🛠️ 功能特性

-   **数据采集**: 支持关键词搜索、地区筛选，自动采集职位详情。
-   **数据分析**: 薪资分布、技能热度、行业趋势分析。
-   **自动化**: 支持模拟登录、自动打招呼（需谨慎使用）。
-   **支付集成**: 支付宝/微信支付接口集成。
-   **安全**: JWT 认证、文件上传安全检测、速率限制。

## ⚠️ 注意事项

-   本用于学习和研究目的，请勿用于非法抓取或攻击目标网站。
-   `IMPLEMENTATION_LOG.md` 记录了近期的安全修复和架构调整。
