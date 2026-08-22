# 一键发布流程

生产环境统一使用 Docker Compose 运行本项目。宿主机只保留 TLS Nginx、
Prometheus/Grafana，以及供其他项目使用的 PostgreSQL 和 Redis；本项目使用独立的
Docker PostgreSQL/Redis，不部署 Elasticsearch。

## 发布命令

在项目根目录执行唯一入口：

```powershell
.\deploy\deploy.ps1
```

该命令依次完成：

1. 运行后端边界/契约/生产安全测试、前端测试和生产构建。
2. 校验 `docker compose` 配置。
3. 要求 Git 工作区干净，将当前分支推送到 `origin`，并锁定精确 commit SHA。
4. 从根目录 `.env` 读取 `remote_ip` 和 `remote_pd`，通过已固定主机密钥的 SSH 登录。
5. 服务器执行 `git fetch`，为该 commit 建立独立 worktree，再构建不可变镜像。
6. 备份 PostgreSQL，执行 Alembic 迁移，启动 API、管理端、实时 worker 和前端。
7. 健康检查通过后切换宿主机 Nginx，并将 Prometheus 目标切到 Docker API。

Git 传输默认使用以下代理：

```dotenv
local_git_proxy=http://127.0.0.1:11123
server_git_proxy=http://127.0.0.1:10809
```

## Runtime services

Each release starts `api`, `admin`, `worker_realtime`, `worker_batch`, `beat`,
and `frontend`. The release check verifies all three Celery containers are
running and uses Celery `inspect ping` to verify both workers can reach Redis.

Agent rollout is explicit in `/opt/job/.env.production`. Set
`AGENT_ENABLED=false`, `AGENT_ROLLOUT_PERCENT=0`, and leave
`AGENT_ROLLOUT_USER_IDS` empty until a rollout is approved. When enabled, use a
non-zero percentage or a non-empty allow-list. The frontend build receives
`VITE_AGENT_ENABLED` from this same production setting.

这两个值可在根目录 `.env` 中覆盖。`local_git_proxy` 只用于本机的 `git push` 和
`git ls-remote`，`server_git_proxy` 只用于服务器的 `git clone` 和 `git fetch`；它们不会
传入应用容器。代理 URL 不允许包含用户名、密码、查询参数或片段，避免凭据进入命令日志或
服务器进程参数。

凭据不会写入 Git、镜像或命令输出。生产配置只保存在服务器
`/opt/job/.env.production`，不会由每次发布上传或覆盖。

支付密钥文件统一放在服务器 `/opt/job/certs`，生产环境变量中的支付宝/微信密钥路径也应
指向该目录。Compose 只读挂载该目录；发布脚本不会生成、上传或打印任何密钥。

## 首次 Docker 切换

首次执行会在镜像构建完成后暂停旧的 Job Supervisor 进程，使用 `pg_dump` 备份宿主机
`job` 数据库，再用 `pg_restore` 导入 Docker PostgreSQL。宿主机 PostgreSQL/Redis
不会停止，因此其他应用不受影响。旧 Job Supervisor 配置只在新服务通过公网健康检查后
才会禁用。

发布会启动实时与批处理队列，以及 `beat` 定时调度器。

## 回滚与备份

远端脚本持有发布锁。构建、备份、迁移、容器启动、Nginx 校验或健康检查任一步失败时，
会自动恢复上一版 Nginx/Prometheus 配置，并重新启动上一版 Docker 镜像；首次切换失败则
恢复旧 Supervisor 服务。

数据库备份保存在 `/opt/job/backups`，版本目录保存在 `/opt/job/releases`，当前版本由
`/opt/job/current` 指向。数据库迁移通常不可自动降级，因此发布前备份是强制步骤。

## 版本规范

- 正常迭代使用语义化版本 `MAJOR.MINOR.PATCH` 和 Git 标签 `vMAJOR.MINOR.PATCH`。
- 每次合并前必须通过 CI；只从已评审且绿色的主分支创建版本标签。
- 服务器实际镜像标签包含发布时间和完整可追溯的 Git SHA，禁止使用 `latest`。
- 紧急情况下可使用 `.\deploy\deploy.ps1 --skip-checks`，使用后必须补跑完整 CI 并记录原因。
- 已确认当前 SHA 推送成功但本机 GitHub 网络异常时，可使用 `--skip-push`；服务器仍会在
  构建前验证该 SHA 能从 `origin` 获取。
- 服务器首次部署无法稳定连接 GitHub 时，使用
  `.\deploy\deploy.ps1 --skip-push --bootstrap-bundle` 通过 Git 原生 bundle 初始化仓库；
  后续版本仍使用普通 `git fetch`。
