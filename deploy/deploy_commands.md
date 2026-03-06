# SFTP/发布命令清单

## 1) 本地一键打包并上传（PowerShell）

在 `d:\Code\job` 执行：

```powershell
$ErrorActionPreference = "Stop"
$Server = "deploy@YOUR_SERVER_IP_OR_DOMAIN"
$RemoteZip = "/opt/job/upload/job_release.zip"

Set-Location d:\Code\job

if (Test-Path .\job_release.zip) { Remove-Item .\job_release.zip -Force }

Compress-Archive `
  -Path .\frontend,.\jobCollectionWebApi,.\common,.\static,.\requirements.txt,.\prometheus.yml,.\grafana,.\deploy `
  -DestinationPath .\job_release.zip `
  -Force

scp .\job_release.zip $Server:$RemoteZip
```

## 2) 服务器一键发布（SSH）

```bash
set -e
cd /opt/job
release_dir=/opt/job/releases/$(date +%Y%m%d_%H%M%S)
mkdir -p "$release_dir"
unzip -q /opt/job/upload/job_release.zip -d "$release_dir"
rsync -a "$release_dir"/ /opt/job/

source /opt/job/jobCollectionWebApi/venv/bin/activate
pip install -r /opt/job/jobCollectionWebApi/requirements.txt

cd /opt/job/frontend
npm ci
npm run build
sudo rsync -av --delete /opt/job/frontend/dist/ /var/www/job/dist/

sudo supervisorctl restart all
sudo supervisorctl status
```

## 3) 本地一条命令上传并远程发布（PowerShell）

```powershell
$ErrorActionPreference = "Stop"
$Server = "deploy@YOUR_SERVER_IP_OR_DOMAIN"

Set-Location d:\Code\job
if (Test-Path .\job_release.zip) { Remove-Item .\job_release.zip -Force }
Compress-Archive -Path .\frontend,.\jobCollectionWebApi,.\common,.\static,.\requirements.txt,.\prometheus.yml,.\grafana,.\deploy -DestinationPath .\job_release.zip -Force
scp .\job_release.zip "$Server:/opt/job/upload/job_release.zip"
ssh $Server 'bash -lc "set -e; cd /opt/job; release_dir=/opt/job/releases/\$(date +%Y%m%d_%H%M%S); mkdir -p \$release_dir; unzip -q /opt/job/upload/job_release.zip -d \$release_dir; rsync -a \$release_dir/ /opt/job/; source /opt/job/jobCollectionWebApi/venv/bin/activate; pip install -r /opt/job/jobCollectionWebApi/requirements.txt; cd /opt/job/frontend; npm ci; npm run build; sudo rsync -av --delete /opt/job/frontend/dist/ /var/www/job/dist/; sudo supervisorctl restart all; sudo supervisorctl status"'
```

## 4) Nginx 配置落地

```bash
sudo cp /opt/job/deploy/nginx/job.conf /etc/nginx/sites-available/job.conf
sudo ln -sf /etc/nginx/sites-available/job.conf /etc/nginx/sites-enabled/job.conf
sudo nginx -t
sudo systemctl reload nginx
```
