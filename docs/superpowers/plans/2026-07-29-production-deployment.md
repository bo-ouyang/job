# Production Server Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 V2 前端、`/api/v2` 后端、Agent 运行时和数据库迁移安全发布到已有 `/opt/job` 生产环境，并完成公网功能验收。

**Architecture:** 保留服务器现有 `/opt/job/.env*`、Python venv、上传目录和共享 Nginx 配置；代码先进入带时间戳 release，再同步到固定运行目录。旧数据库由 `create_tables()` 建立且没有 Alembic 版本，因此先备份并 stamp `20260201_00`，再按迁移链升级到 `20260728_02`。Supervisor 只启动 API 和 Agent 所需 realtime Worker；batch、Beat 和爬虫保持关闭。手工启动的 Nginx master 使用 `nginx -s reload`，不通过 systemd 重启。

**Tech Stack:** Windows PowerShell、Python Paramiko/SFTP、FastAPI/Uvicorn、Celery/Supervisor、PostgreSQL 15、Alembic、Vue/Vite、Nginx

---

### Task 1: 本地发布产物验证

**Files:**
- Read: `D:/Code/job/.env`
- Build: `D:/Code/job/frontend/dist/`
- Create: `D:/Code/job/.deploy/job-release.tar.gz`

- [ ] **Step 1: 运行维护测试**

Run: `pytest tests -q`

Expected: `67 passed`。

- [ ] **Step 2: 以生产 API 根路径构建前端**

```powershell
$env:VITE_API_BASE_URL='/api/v1'
$env:VITE_API_V2_BASE_URL='/api/v2'
Set-Location D:\Code\job\frontend
npm test
npm run build
```

Expected: 42 项测试通过，`dist/index.html` 生成，构建产物不包含 `localhost:8000`。

- [ ] **Step 3: 生成不含密钥和依赖缓存的发布包**

发布包包含 `common/`、`jobCollectionWebApi/`、`alembic/`、`alembic.ini`、根 `requirements.txt`、`frontend/` 和已构建 `frontend/dist/`；排除 `.env*`、`.git`、`node_modules`、`venv`、`__pycache__`、测试缓存与用户上传。

Expected: `.deploy/job-release.tar.gz` 可列出且不包含 `.env`、`remote_pd` 或 `node_modules`。

### Task 2: 远程备份与发布目录

**Remote paths:**
- Existing app: `/opt/job`
- Release: `/opt/job/releases/<release_id>`，其中 `release_id=$(date +%Y%m%d_%H%M%S)`
- Backup: `/opt/job/backups/<release_id>`
- Upload: `/opt/job/upload/job-release.tar.gz`

- [ ] **Step 1: 备份现有代码、前端和进程配置**

备份 `/opt/job/common`、`/opt/job/jobCollectionWebApi`、`/opt/job/frontend`、`/var/www/job/dist`、`/etc/supervisor/conf.d/jobcollection.conf` 和 `/etc/nginx/sites-enabled/job.conf`。

Expected: 备份目录存在且文件数非零。

- [ ] **Step 2: 备份 PostgreSQL**

从 `/opt/job/.env.production` 读取 PostgreSQL 参数，通过 `pg_dump -Fc` 写入 `/opt/job/backups/<release_id>/database.dump`。

Expected: `pg_restore --list database.dump` 成功，备份文件大小大于 0。

- [ ] **Step 3: 上传并解压 release**

使用 SFTP 上传到 `/opt/job/upload/job-release.tar.gz`，解压到 `/opt/job/releases/<release_id>`。

Expected: release 中存在 `alembic.ini`、`jobCollectionWebApi/main.py` 和 `frontend/dist/index.html`。

### Task 3: 同步代码和 Python 依赖

**Remote paths:**
- Runtime: `/opt/job`
- Venv: `/opt/job/jobCollectionWebApi/venv`

- [ ] **Step 1: 同步后端和前端源码**

分别用 `rsync -a --delete` 同步 `common/`、`alembic/`、`jobCollectionWebApi/` 和 `frontend/`；同步 `jobCollectionWebApi/` 时排除 `venv/`，同步根文件时不覆盖 `.env` 与 `.env.production`。

Expected: `/opt/job/.env*` 的时间和校验值保持不变，`jobCollectionWebApi/api/v2/api.py` 已存在。

- [ ] **Step 2: 安装依赖并检查环境**

```bash
/opt/job/jobCollectionWebApi/venv/bin/pip install -r /opt/job/requirements.txt
/opt/job/jobCollectionWebApi/venv/bin/pip check
```

Expected: Alembic 可导入且 `pip check` 无冲突。

### Task 4: 数据库版本迁移

**Remote files:**
- `/opt/job/alembic.ini`
- `/opt/job/alembic/versions/*.py`

- [ ] **Step 1: 标记旧 schema baseline**

```bash
cd /opt/job
ENVIRONMENT=production PYTHONPATH=/opt/job /opt/job/jobCollectionWebApi/venv/bin/alembic stamp 20260201_00
```

Expected: `alembic_version` 为 `20260201_00`，旧表和行数不变。

- [ ] **Step 2: 升级到唯一 head**

```bash
ENVIRONMENT=production PYTHONPATH=/opt/job /opt/job/jobCollectionWebApi/venv/bin/alembic upgrade head
```

Expected: head 为 `20260728_02`；Agent、课程、技能、变更记录表及 Agent 计费列存在。

- [ ] **Step 3: 初始化缺失的 AI 定价产品**

```bash
ENVIRONMENT=production PYTHONPATH=/opt/job /opt/job/jobCollectionWebApi/venv/bin/python /opt/job/jobCollectionWebApi/init_products.py
```

Expected: 操作幂等，已有产品不被重复创建。

### Task 5: 启动前后端并保持爬虫关闭

**Remote configs:**
- `/etc/supervisor/conf.d/jobcollection.conf`
- `/etc/nginx/sites-enabled/job.conf`
- `/var/www/job/dist`

- [ ] **Step 1: 禁用批处理/定时任务并启动 API 与 realtime Worker**

```bash
supervisorctl reread
supervisorctl update
supervisorctl stop job-celery-batch job-celery-beat
supervisorctl start job-api job-celery-realtime
```

Expected: `job-api`、`job-celery-realtime` 为 `RUNNING` 且稳定超过 15 秒；`job-celery-batch`、`job-celery-beat` 为 `STOPPED` 且 `autostart=false`。

- [ ] **Step 2: 验证本机后端**

Run: `curl -fsS http://127.0.0.1:8000/health`，并检查 `/api/v2/market/dashboard` 和 `/api/v2/ai/pricing`。

Expected: 健康接口 200；V2 市场与定价接口返回统一成功响应。

- [ ] **Step 3: 原子发布静态前端**

将 `/opt/job/frontend/dist/` 同步到 `/var/www/job/dist/`，执行 `nginx -t` 后对现有 master 执行 `nginx -s reload`。

Expected: 保留 `/paper`、`/django` 路由；首页 HTML 和新版静态资源可访问。

### Task 6: 公网和浏览器验收

**Target:** `.env` 的 `remote_ip` 对应 HTTPS 站点

- [ ] **Step 1: 公网 HTTP 验证**

检查 `/`、`/api/v2/market/dashboard`、`/api/v2/ai/pricing`、`/api/v1/jobs`、不存在路径的 SPA fallback，以及 HTTP→HTTPS 跳转。

Expected: 页面/API 状态正确，无 502；V1 与 V2 同时可用。

- [ ] **Step 2: 浏览器桌面端验收**

打开首页，确认字体、图表、筛选、右下角 AI 对话框和职业分析入口正常；检查控制台错误、失败请求和横向溢出。

- [ ] **Step 3: 登录后验收**

验证登录、个人资料读取/保存、课程技能集合、职业分析、AI 提交与余额不足 402 跳转；若没有可用测试账号，只执行不改用户数据的认证边界检查并记录限制。

### Rollback

若迁移前失败：恢复备份代码和前端后重启 Supervisor。

若迁移后应用失败：先保留数据库新表（V1 兼容且不影响旧数据），恢复旧代码和前端；只有确认必须回退 schema 时，才在停服状态下执行 `alembic downgrade 20260201_00` 或从 `database.dump` 恢复。任何数据库恢复前必须再次确认备份可读。
