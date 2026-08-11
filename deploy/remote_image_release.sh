#!/usr/bin/env bash
set -Eeuo pipefail

repository_url=${1:?repository URL is required}
commit=${2:?commit SHA is required}
release_id=${3:?release id is required}
server_name=${4:?server name is required}
backend_image=${5:?backend image is required}
frontend_image=${6:?frontend image is required}
server_git_proxy=${7:-http://127.0.0.1:10809}

base_dir=/opt/job
release_dir="$base_dir/releases/$release_id"
repository_dir="$base_dir/repository"
backup_dir="$base_dir/backups"
state_dir="$base_dir/.deploy/state"
current_link="$base_dir/current"
production_env_path=/opt/job/.env.production
supervisor_config=/etc/supervisor/conf.d/jobcollection.conf
supervisor_disabled=/etc/supervisor/conf.d/jobcollection.conf.disabled
nginx_config=/etc/nginx/sites-available/job.conf
prometheus_config=/etc/prometheus/prometheus.yml
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
database_backup="$backup_dir/job-$release_id.dump"
nginx_backup="$state_dir/nginx-$release_id.conf"
prometheus_backup="$state_dir/prometheus-$release_id.yml"
previous_release=""
legacy_stopped=0
nginx_changed=0
prometheus_changed=0
supervisor_disabled_now=0
committed=0

mkdir -p "$base_dir/releases" "$backup_dir" "$state_dir" /opt/job/certs
chmod 700 "$backup_dir" "$state_dir" /opt/job/certs
exec 9>"$base_dir/.deploy/release.lock"
if ! flock -n 9; then
    echo "Another release is already running." >&2
    exit 1
fi

if [[ -L "$current_link" ]]; then
    previous_release=$(readlink -f "$current_link")
fi

git_with_retry() {
    local attempt
    for attempt in 1 2 3; do
        if timeout --signal=TERM 120 git -c http.version=HTTP/1.1 \
            -c http.proxy="$server_git_proxy" "$@"; then
            return 0
        fi
        if (( attempt < 3 )); then
            echo "Git transfer failed (attempt $attempt/3); retrying..." >&2
            sleep $((attempt * 2))
        fi
    done
    return 1
}

docker_pull_with_retry() {
    local image=$1
    local attempt
    for attempt in 1 2 3; do
        if timeout --signal=TERM 300 docker pull "$image"; then
            return 0
        fi
        if (( attempt < 3 )); then
            echo "Image pull failed (attempt $attempt/3); retrying..." >&2
            sleep $((attempt * 2))
        fi
    done
    return 1
}

backup_running_database() {
    local output_path=$1
    local current_db_user
    local current_db_name
    [[ $(docker inspect -f '{{.State.Running}}' job_postgres 2>/dev/null) == true ]]
    current_db_user=$(docker exec job_postgres sh -c 'printf %s "$POSTGRES_USER"')
    current_db_name=$(docker exec job_postgres sh -c 'printf %s "$POSTGRES_DB"')
    docker exec job_postgres pg_dump --format=custom \
        -U "$current_db_user" "$current_db_name" > "$output_path"
    chmod 600 "$output_path"
}

compose_new() {
    (
        cd "$release_dir"
        BACKEND_IMAGE="$backend_image" FRONTEND_IMAGE="$frontend_image" \
            docker compose --env-file .env.production "$@"
    )
}

start_previous_release() {
    [[ -n "$previous_release" && -f "$previous_release/.release.env" ]] || return 1
    (
        cd "$previous_release"
        set -a
        source .release.env
        set +a
        docker compose --env-file .env.production up -d --remove-orphans \
            api admin worker_realtime frontend
    )
}

start_legacy_services() {
    if [[ -f "$supervisor_disabled" && ! -f "$supervisor_config" ]]; then
        mv "$supervisor_disabled" "$supervisor_config"
        supervisorctl reread >/dev/null || true
        supervisorctl update >/dev/null || true
    fi
    supervisorctl start job-api job-admin job-celery-realtime >/dev/null || true
}

rollback() {
    status=$?
    trap - ERR INT TERM
    if (( committed == 0 )); then
        echo "Release failed; rollback is starting." >&2
        set +e
        if (( nginx_changed == 1 )) && [[ -f "$nginx_backup" ]]; then
            cp "$nginx_backup" "$nginx_config"
            nginx -t && nginx -s reload
        fi
        if (( prometheus_changed == 1 )) && [[ -f "$prometheus_backup" ]]; then
            cp "$prometheus_backup" "$prometheus_config"
            promtool check config "$prometheus_config" >/dev/null 2>&1 || true
            pkill -HUP -x prometheus >/dev/null 2>&1 || true
        fi
        if ! start_previous_release; then
            compose_new stop api admin worker_realtime frontend >/dev/null 2>&1 || true
            if (( legacy_stopped == 1 || supervisor_disabled_now == 1 )); then
                start_legacy_services
            fi
        fi
        echo "Rollback finished." >&2
    fi
    exit "$status"
}
trap rollback ERR INT TERM

echo "[1/8] Checking out exact Git commit $commit"
[[ -f "$production_env_path" ]] || { echo "Missing $production_env_path" >&2; exit 1; }
if [[ ! -d "$repository_dir/.git" ]]; then
    if [[ -e "$repository_dir" ]]; then
        mv "$repository_dir" "$repository_dir.incomplete-$timestamp"
    fi
    git_with_retry clone --depth=1 --no-checkout "$repository_url" "$repository_dir"
else
    git -C "$repository_dir" remote set-url origin "$repository_url"
fi
(
    cd "$repository_dir"
    if ! git cat-file -e "$commit^{commit}" 2>/dev/null; then
        git_with_retry fetch --depth=1 --prune origin "$commit"
    fi
    git cat-file -e "$commit^{commit}"
    [[ $(git rev-parse "$commit^{commit}") == "$commit" ]]
    git worktree prune
    git worktree add --detach "$release_dir" "$commit"
)
install -m 600 "$production_env_path" "$release_dir/.env.production"

host_nginx_template="$release_dir/deploy/nginx/host.conf"
host_prometheus_template="$release_dir/deploy/prometheus/prometheus.yml"
[[ -f "$host_nginx_template" ]] || { echo "Missing host Nginx template" >&2; exit 1; }
[[ -f "$host_prometheus_template" ]] || { echo "Missing Prometheus template" >&2; exit 1; }

printf 'BACKEND_IMAGE=%q\nFRONTEND_IMAGE=%q\n' \
    "$backend_image" "$frontend_image" > "$release_dir/.release.env"
chmod 600 "$release_dir/.release.env"

echo "[2/8] Pulling and verifying immutable release images"
docker_pull_with_retry "$backend_image"
docker_pull_with_retry "$frontend_image"
backend_revision=$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$backend_image")
frontend_revision=$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$frontend_image")
[[ "$backend_revision" == "$commit" ]]
[[ "$frontend_revision" == "$commit" ]]
compose_new config --quiet
compose_new run --rm --no-deps api python -c "import jobCollectionWebApi.main; import jobCollectionWebApi.main_admin; import jobCollectionWebApi.worker"

echo "[3/8] Starting isolated data services"
if [[ -f "$state_dir/docker-database-initialized" ]]; then
    echo "Backing up the currently running Docker PostgreSQL database before reconciliation"
    backup_running_database "$database_backup"
fi
compose_new up -d db redis
for _ in $(seq 1 30); do
    if [[ $(docker inspect -f '{{.State.Health.Status}}' job_postgres 2>/dev/null || true) == healthy ]] && \
       [[ $(docker inspect -f '{{.State.Health.Status}}' job_redis 2>/dev/null || true) == healthy ]]; then
        break
    fi
    sleep 2
done
[[ $(docker inspect -f '{{.State.Health.Status}}' job_postgres) == healthy ]]
[[ $(docker inspect -f '{{.State.Health.Status}}' job_redis) == healthy ]]

db_user=$(docker exec job_postgres sh -c 'printf %s "$POSTGRES_USER"')
db_name=$(docker exec job_postgres sh -c 'printf %s "$POSTGRES_DB"')

if [[ ! -f "$state_dir/docker-database-initialized" ]]; then
    echo "[4/8] Stopping legacy Job processes and importing the host database"
    supervisorctl stop job-api job-admin job-celery-realtime job-celery-batch job-celery-beat >/dev/null || true
    legacy_stopped=1
    runuser -u postgres -- pg_dump --format=custom "$db_name" > "$database_backup"
    docker exec job_postgres dropdb --if-exists --force -U "$db_user" "$db_name"
    docker exec job_postgres createdb -U "$db_user" "$db_name"
    docker exec -i job_postgres pg_restore --exit-on-error --no-owner --no-privileges \
        -U "$db_user" -d "$db_name" < "$database_backup"
else
    echo "[4/8] Current Docker PostgreSQL backup already recorded"
fi
chmod 600 "$database_backup"

echo "[5/8] Running database migrations"
compose_new run --rm migration

echo "[6/8] Starting API, admin, realtime worker, and frontend"
compose_new up -d --remove-orphans api admin worker_realtime frontend
curl --fail --silent --show-error --retry 30 --retry-all-errors --retry-delay 2 \
    http://127.0.0.1:18080/health >/dev/null
curl --fail --silent --show-error --retry 10 --retry-all-errors --retry-delay 2 \
    http://127.0.0.1:18002/admin/ >/dev/null
[[ $(docker inspect -f '{{.State.Running}}' job_worker_realtime) == true ]]

echo "[7/8] Switching host Nginx and Prometheus"
cp "$nginx_config" "$nginx_backup"
sed "s/__SERVER_NAME__/$server_name/g" "$host_nginx_template" > "$nginx_config"
nginx_changed=1
nginx -t
nginx -s reload

cp "$prometheus_config" "$prometheus_backup"
cp "$host_prometheus_template" "$prometheus_config"
prometheus_changed=1
promtool check config "$prometheus_config"
pkill -HUP -x prometheus >/dev/null 2>&1 || true

curl --fail --silent --show-error --retry 10 --retry-all-errors --retry-delay 2 \
    --resolve "$server_name:443:127.0.0.1" "https://$server_name/health" --insecure >/dev/null

echo "[8/8] Recording the release and disabling legacy Supervisor programs"
ln -sfn "$release_dir" "$current_link"
touch "$state_dir/docker-database-initialized"
if [[ -f "$supervisor_config" ]]; then
    mv "$supervisor_config" "$supervisor_disabled"
    supervisor_disabled_now=1
    supervisorctl reread >/dev/null || true
    supervisorctl update >/dev/null || true
fi

committed=1
trap - ERR INT TERM
echo "Release $release_id completed successfully."
BACKEND_IMAGE="$backend_image" FRONTEND_IMAGE="$frontend_image" \
    docker compose -f "$release_dir/docker-compose.yml" \
    --env-file "$release_dir/.env.production" ps
