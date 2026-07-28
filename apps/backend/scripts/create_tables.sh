#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
用法:
  ./scripts/create_tables.sh [命令] [参数]

命令:
  upgrade [revision]  执行迁移，默认升级到 head（默认命令）
  current             查看当前数据库版本
  history             查看迁移历史
  check               检查模型是否存在未生成的迁移
  downgrade <revision>回退到指定版本，例如 -1 或 20260725_0008
  stamp <revision>    将数据库标记为指定版本，不执行迁移
  help                显示帮助

环境:
  脚本使用 apps/backend/.env 中的 DATABASE_URL，或 DB_USER、DB_PASSWORD、
  DB_HOST、DB_PORT、DB_NAME 组合生成数据库连接。
EOF
}

run_alembic() {
  if [[ -x "${BACKEND_DIR}/.venv/bin/alembic" ]]; then
    (cd "${BACKEND_DIR}" && "${BACKEND_DIR}/.venv/bin/alembic" -c alembic.ini "$@")
  elif command -v poetry >/dev/null 2>&1; then
    (cd "${BACKEND_DIR}" && poetry run alembic -c alembic.ini "$@")
  else
    echo "错误：找不到 Alembic。请先安装后端依赖，或安装 Poetry。" >&2
    exit 1
  fi
}

COMMAND="${1:-upgrade}"

case "${COMMAND}" in
  upgrade|create)
    run_alembic upgrade "${2:-head}"
    echo "数据库迁移已执行完成。"
    ;;
  current)
    run_alembic current
    ;;
  history)
    run_alembic history
    ;;
  check)
    run_alembic check
    ;;
  downgrade)
    if [[ -z "${2:-}" ]]; then
      echo "错误：downgrade 需要目标版本，例如 -1。" >&2
      usage >&2
      exit 2
    fi
    run_alembic downgrade "$2"
    ;;
  stamp)
    if [[ -z "${2:-}" ]]; then
      echo "错误：stamp 需要目标版本。" >&2
      usage >&2
      exit 2
    fi
    run_alembic stamp "$2"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "错误：未知命令 ${COMMAND}" >&2
    usage >&2
    exit 2
    ;;
esac
