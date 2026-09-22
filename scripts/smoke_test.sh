#!/usr/bin/env bash
# 阶段 F：一键回归 docs/smoke-test.md 里的后端条目。
# JSON 走 python/httpx（PowerShell curl -d "{\"k\":1}" 会把引号吃掉）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
export SMOKE_BASE="${SMOKE_BASE:-http://127.0.0.1:8000}"

if ! command -v python >/dev/null 2>&1; then
  echo "需要 python（conda RAG_study）在 PATH 中" >&2
  exit 1
fi

python -m scripts.smoke_test
