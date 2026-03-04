#!/bin/bash
# =============================================================================
# 招聘系统 Ubuntu 原生环境一键部署与配置脚本
# 仅支持 Debian/Ubuntu 系 Linux 发行版
# =============================================================================

set -e

# =============================================================================
# 1. 基础依赖与环境准备
# =============================================================================
echo ">>> 开始更新系统并安装基础依赖..."
sudo apt-get update -y
sudo apt-get install -y wget curl gnupg software-properties-common apt-transport-https lsb-release vim git build-essential supervisor

# =============================================================================
# 2. 安装 PostgreSQL 15
# =============================================================================
echo ">>> 安装 PostgreSQL 15..."
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
sudo apt-get update -y
sudo apt-get install -y postgresql-15 postgresql-contrib-15

# 配置 PostgreSQL 允许外部连接 (为本地爬虫准备)
echo ">>> 配置 PostgreSQL 允许远程连接..."
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" /etc/postgresql/15/main/postgresql.conf
echo "host    all             all             0.0.0.0/0               scram-sha-256" | sudo tee -a /etc/postgresql/15/main/pg_hba.conf

sudo systemctl restart postgresql
sudo systemctl enable postgresql

# 初始化数据库与用户
# 请在部署后手动修改密码
echo ">>> 初始化 job 数据库和用户..."
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'your_db_password';" || true
sudo -u postgres psql -c "CREATE DATABASE job OWNER postgres;" || true

# =============================================================================
# 3. 安装 Redis
# =============================================================================
echo ">>> 安装 Redis..."
sudo apt-get install -y redis-server
# 配置 Redis 允许外部连接和设置密码
echo ">>> 配置 Redis 允许远程连接..."
sudo sed -i "s/bind 127.0.0.1 -::1/bind 0.0.0.0/g" /etc/redis/redis.conf
sudo sed -i "s/bind 127.0.0.1/# bind 127.0.0.1/g" /etc/redis/redis.conf
sudo sed -i "s/# requirepass foobared/requirepass your_redis_password/g" /etc/redis/redis.conf

sudo systemctl restart redis-server
sudo systemctl enable redis-server

# =============================================================================
# 4. 安装 Elasticsearch 8.x
# =============================================================================
echo ">>> 安装 Elasticsearch 8.x..."
wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo gpg --dearmor -o /usr/share/keyrings/elasticsearch-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/elasticsearch-keyring.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-8.x.list
sudo apt-get update -y
sudo apt-get install -y elasticsearch

# 配置 ES 内存限制 (推荐服务器至少8G内存，这里限制ES使用2G)
echo "-Xms2g" | sudo tee /etc/elasticsearch/jvm.options.d/memory.options
echo "-Xmx2g" | sudo tee -a /etc/elasticsearch/jvm.options.d/memory.options

# (可选) 关闭安全或配置简单网络
# sudo sed -i 's/xpack.security.enabled: true/xpack.security.enabled: false/g' /etc/elasticsearch/elasticsearch.yml

sudo systemctl restart elasticsearch
sudo systemctl enable elasticsearch

# =============================================================================
# 5. 安装 Prometheus
# =============================================================================
echo ">>> 安装 Prometheus..."
# 检查默认包能否安装，如果不行为手动下载
sudo apt-get install -y prometheus

# =============================================================================
# 6. 安装 Grafana
# =============================================================================
echo ">>> 安装 Grafana..."
sudo mkdir -p /etc/apt/keyrings/
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update -y
sudo apt-get install -y grafana
sudo systemctl enable grafana-server
sudo systemctl restart grafana-server

# =============================================================================
# 7. 安装 Python 3.10 环境
# =============================================================================
echo ">>> 检查/安装 Python 3.10..."
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip

# 在当前目录创建虚拟环境，假设当前目录就是部署目录
echo ">>> 创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python3.10 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    echo ">>> 安装 Python 依赖库..."
    pip install -r requirements.txt
else
    echo "警告: 未找到 requirements.txt"
fi

# 安装额外的性能分析工具 py-spy
echo ">>> 安装 py-spy..."
pip install py-spy

# =============================================================================
# 8. 安装与配置 Nginx
# =============================================================================
echo ">>> 安装 Nginx..."
sudo apt-get install -y nginx

# =============================================================================
# 9. 生成 Supervisor 进程管理配置
# =============================================================================
echo ">>> 生成 Supervisor 进程配置文件..."
PROJECT_DIR=$(pwd)
USER_NAME=$(whoami)

# 创建 logs 目录用于 supervisor 记录输出
mkdir -p "$PROJECT_DIR/logs"

cat <<EOF | sudo tee /etc/supervisor/conf.d/job_collection.conf
[program:job-api]
command=$PROJECT_DIR/venv/bin/uvicorn jobCollectionWebApi.main:app --host 127.0.0.1 --port 8000
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/job_api_out.log
environment=PATH="$PROJECT_DIR/venv/bin"

[program:job-admin]
command=$PROJECT_DIR/venv/bin/uvicorn jobCollectionWebApi.main_admin:app --host 127.0.0.1 --port 8001
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/job_admin_out.log
environment=PATH="$PROJECT_DIR/venv/bin"

[program:job-celery-worker-batch]
command=$PROJECT_DIR/venv/bin/celery -A jobCollectionWebApi.worker.celery_app worker -Q batch --loglevel=info
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/job_celery_worker_batch_out.log
environment=PATH="$PROJECT_DIR/venv/bin"

[program:job-celery-worker-realtime]
command=$PROJECT_DIR/venv/bin/celery -A jobCollectionWebApi.worker.celery_app worker -Q realtime --loglevel=info
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/job_celery_worker_realtime_out.log
environment=PATH="$PROJECT_DIR/venv/bin"

[program:job-celery-beat]
command=$PROJECT_DIR/venv/bin/celery -A jobCollectionWebApi.worker.celery_app beat --loglevel=info
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=$PROJECT_DIR/logs/job_celery_beat_out.log
environment=PATH="$PROJECT_DIR/venv/bin"
EOF

echo ">>> 重新加载 Supervisor 配置并启动业务服务..."
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart all

echo "=========================================================================="
echo "✅ 部署环境初始化完成！"
echo "接下来请确认以下操作："
echo "1. 修改 /etc/postgresql/15/main/pg_hba.conf 以及云服务器安全组策略，确保您本地电脑能够连接 5432 和 6379。"
echo "2. 修改 $PROJECT_DIR/.env 中的连接配置。"
echo "3. 检查 Prometheus (默认: http://IP:9090) 和 Grafana (默认: http://IP:3000) 的网页是否可以访问。"
echo "4. 根据 Nginx 配置代理前端 dist 文件到 80 端口。"
echo "=========================================================================="
