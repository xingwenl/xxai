#!/usr/bin/env bash
#
# 开发环境一键重置：清数据 → 清磁盘 → 清 Redis → 灌种子。
#
# 用法：
#   bash apps/backend/scripts/reset_dev_db.sh              # 清数据并重新灌种子
#   bash apps/backend/scripts/reset_dev_db.sh --rebuild    # 额外重建库结构（DROP SCHEMA + alembic upgrade head）
#   bash apps/backend/scripts/reset_dev_db.sh --no-seed    # 只清空，不灌种子
#   bash apps/backend/scripts/reset_dev_db.sh --local      # 用本机 .venv 跑种子，而不是容器
#
# 这不是给生产用的脚本：它会**不可逆地**清空本地开发库的全部数据、清空
# `apps/backend/storage/` 的全部派生态文件、并对 Redis DB 0 执行 FLUSHDB。
# 背景与验收方式见 docs/runbooks/dev-environment.md。
#
# 设计约束：所有数据库与 Redis 操作都在容器内执行（用容器自己的
# POSTGRES_USER / POSTGRES_DB 环境变量），避免宿主机 apps/backend/.env 与
# 仓库根 .env 两套配置漂移导致「清的不是正在跑的那个库」。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
STORAGE_DIR="${ROOT}/apps/backend/storage"

REBUILD=0
RUN_SEED=1
USE_CONTAINER=1

usage() {
  cat <<'USAGE'
开发环境一键重置：清数据 → 清磁盘 → 清 Redis → 灌种子。

用法：bash apps/backend/scripts/reset_dev_db.sh [选项]

选项：
  --rebuild    先 DROP SCHEMA public 再由迁移重建库结构（等价于换一份全新库）
  --no-seed    只清空，不灌种子
  --local      用 apps/backend/.venv/bin/python 跑种子，而不是走容器
  -h, --help   显示本帮助
USAGE
}

step() { printf '\n==> %s\n' "$1"; }
die() { printf '错误：%s\n' "$1" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1 ;;
    --no-seed) RUN_SEED=0 ;;
    --local) USE_CONTAINER=0 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf '错误：未知参数 %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "${ROOT}/docker-compose.yml" ]]; then
  die "${ROOT} 下找不到 docker-compose.yml，请在仓库内运行本脚本"
fi
cd "${ROOT}" || die "无法进入 ${ROOT}"

# 清空 public 下所有表的数据，只留 alembic_version（保留迁移版本，下次不用重建结构）。
# RESTART IDENTITY 把自增序号也复位，这样重置后平台/Agent 又从 1 开始，
# 根 .env 里的 EMBED_AGENT_ID=1 之类固定引用继续有效。
truncate_database() {
  step "清空数据库数据（保留 alembic_version，自增序号复位）"
  docker compose exec -T db sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL' || die "清库失败"
DO $$
DECLARE stmt text;
BEGIN
  SELECT 'TRUNCATE TABLE '
         || string_agg(format('%I.%I', schemaname, tablename), ', ')
         || ' RESTART IDENTITY CASCADE'
    INTO stmt
    FROM pg_tables
   WHERE schemaname = 'public' AND tablename <> 'alembic_version';
  IF stmt IS NOT NULL THEN
    EXECUTE stmt;
  END IF;
END
$$;
SQL
}

# storage/ 下全部内容都是数据库行的派生态（技能包解压目录、附件、知识库上传件），
# 清库之后它们只会变成孤儿文件，所以整体清掉，而不是逐个列举子目录留下漏网的。
clean_storage() {
  step "清空磁盘派生态 ${STORAGE_DIR}"
  if [[ "${STORAGE_DIR}" != "${ROOT}/apps/backend/storage" || ! -d "${STORAGE_DIR}" ]]; then
    die "存储目录不符合预期，为避免误删已中止：${STORAGE_DIR}"
  fi
  find "${STORAGE_DIR}" -mindepth 1 -maxdepth 1 -print -exec rm -rf {} +
}

# 配额计数（RedisQuotaStore）与网关事件回放流（Redis Stream）都在 DB 0 上，
# 清库不连带清掉它们会出现「库是空的但配额已经用完」这类鬼状态。
flush_redis() {
  step "清空 Redis DB 0（配额计数与事件回放流）"
  docker compose exec -T redis redis-cli FLUSHDB || die "清 Redis 失败"
}

rebuild_schema() {
  step "重建库结构（DROP SCHEMA public → alembic upgrade head）"
  docker compose exec -T db sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"' \
    || die "重建 schema 失败"
  # 结构走镜像里的 alembic（与 api 容器启动时同一条命令），不用宿主机 venv。
  docker compose run --rm --no-deps api alembic upgrade head || die "alembic upgrade head 失败"
}

run_seed() {
  step "灌入开发环境种子"
  if [[ "${USE_CONTAINER}" -eq 1 ]]; then
    # 把工作区的 scripts/ 只读挂进一次性容器：种子脚本与 skill 源文件随仓库改动生效，
    # 不需要先 docker compose build api。app/ 仍来自镜像，用它跑 `python -m`（而不是
    # `python scripts/xxx.py`）才能让 /app 进 sys.path 从而 import app。
    docker compose run --rm --no-deps \
      -v "${ROOT}/apps/backend/scripts:/app/scripts:ro" \
      api python -m scripts.seed_dev_env || die "种子脚本失败"
  else
    (cd "${ROOT}/apps/backend" && .venv/bin/python -m scripts.seed_dev_env) || die "种子脚本失败"
  fi
}

if [[ "${REBUILD}" -eq 1 ]]; then
  rebuild_schema
fi

truncate_database
clean_storage
flush_redis

if [[ "${RUN_SEED}" -eq 1 ]]; then
  run_seed
else
  step "已跳过种子（--no-seed）"
fi

printf '\n==> 重置完成\n'
