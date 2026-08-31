#!/usr/bin/env bash
# ai-base 备份脚本：PostgreSQL 全量 + 附件存储目录，保留最近 N 份
# 用法：
#   bash deploy/backup.sh                 # 手动备份一次
#   bash deploy/backup.sh --install-cron  # 安装每日 02:30 自动备份
# 可用环境变量：BACKUP_DIR（默认 /root/backups/ai-base）、KEEP_DAYS（默认 7）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILES=(-f "$REPO_ROOT/docker-compose.yml" -f "$REPO_ROOT/deploy/docker-compose.prod.yml")

BACKUP_DIR="${BACKUP_DIR:-/root/backups/ai-base}"
KEEP_DAYS="${KEEP_DAYS:-7}"

cd "$REPO_ROOT"
[[ -f .env ]] || { echo "[错误] 缺少 .env，请先运行 deploy.sh 完成部署"; exit 1; }

# 优先使用 Docker Compose v2 插件（Docker 26 自带），其次独立 docker-compose 二进制
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "[错误] 缺少 docker compose，请先运行：bash deploy/install-docker.sh"
  exit 1
fi

get_env() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
DB_USER="$(get_env DB_USER)"; DB_USER="${DB_USER:-root}"
DB_NAME="$(get_env DB_NAME)"; DB_NAME="${DB_NAME:-ai_db}"

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"

echo "==> 备份数据库 $DB_NAME -> $BACKUP_DIR/db-$TS.sql"
# 容器内通过 unix socket 连接，官方 postgres 镜像默认 trust，无需密码
"${DC[@]}" "${COMPOSE_FILES[@]}" exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" \
  > "$BACKUP_DIR/db-$TS.sql"

echo "==> 备份附件存储 -> $BACKUP_DIR/storage-$TS.tar.gz"
tar czf "$BACKUP_DIR/storage-$TS.tar.gz" -C "$REPO_ROOT" apps/backend/storage 2>/dev/null || \
  echo "[警告] 附件目录为空或不存在，跳过（可忽略）"

echo "==> 清理超过 ${KEEP_DAYS} 天的旧备份"
find "$BACKUP_DIR" -name 'db-*.sql' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'storage-*.tar.gz' -mtime +"$KEEP_DAYS" -delete

echo "备份完成：$BACKUP_DIR"
ls -lh "$BACKUP_DIR" | tail -5

if [[ "${1:-}" == "--install-cron" ]]; then
  CRON_LINE="30 2 * * * bash $SCRIPT_DIR/backup.sh >> $BACKUP_DIR/backup.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v "deploy/backup.sh" ; echo "$CRON_LINE" ) | crontab -
  echo "已安装每日 02:30 自动备份任务（crontab）。"
  echo "提示：建议定期把 $BACKUP_DIR 下载到本地或对象存储，避免与服务器同毁。"
fi
