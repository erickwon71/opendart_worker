#!/bin/zsh
set -euo pipefail

cd /Users/taejin/Project/dart_finance || exit 1
source ./venv/bin/activate

# ✅ Python 실행 중에는 Sleep 방지
caffeinate -s python scripts/06_run_financial_worker.py