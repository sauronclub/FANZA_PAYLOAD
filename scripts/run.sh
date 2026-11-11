#!/usr/bin/env bash
# ============================================================
# FANZA GraphQL Payload 捕获器 —— 手动运行入口
# 用法：
#   ./scripts/run.sh                  # 捕获全部启用的页面
#   ./scripts/run.sh --only MOVIE_DETAIL
#   ./scripts/run.sh --list
# 说明：脚本会自动切到项目根目录，并优先使用 .venv 中的解释器。
# ============================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

exec "$PYTHON" main.py "$@"
