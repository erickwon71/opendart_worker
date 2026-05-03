#!/bin/zsh

set -e
set -o pipefail   # ⭐️ 핵심: 파이프 중간 실패도 실패로 인식

LOG_DIR="$HOME/Project/dart_finance/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/pipeline_$(date +%Y%m%d_%H%M%S).log"

echo "▶ Pipeline started at $(date)" | tee -a "$LOG_FILE"

PYTHON_BIN="$(which python)"

cd "$HOME/Project/dart_finance"

echo "▶ 1) Backfill induty_code" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_0_backfill_induty_code.py | tee -a "$LOG_FILE"

echo "▶ 2) Append investment rules" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_1_append_investment_rules_universal.py | tee -a "$LOG_FILE"

echo "▶ 3) Account standardize" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_1_account_standardize_all.py | tee -a "$LOG_FILE"

echo "▶ 4) Build DuckDB mart" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_2_build_duckdb_mart.py | tee -a "$LOG_FILE"

echo "▶ 5) Build industry auto CAPEX mart" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_3_rebuild_cash_mart_industry_auto_universal.py | tee -a "$LOG_FILE"

echo "▶ 6) Build 10y earning power" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/08_4_build_buffett_earning_power_10y.py | tee -a "$LOG_FILE"

echo "▶ 7) Build yearly scores" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/09_6_build_yearly_scores.py | tee -a "$LOG_FILE"

echo "▶ 8) Generate Top20 HTML reports" | tee -a "$LOG_FILE"
$PYTHON_BIN scripts/10_3_batch_top20_html_reports.py | tee -a "$LOG_FILE"

echo "✅ Pipeline finished at $(date)" | tee -a "$LOG_FILE"