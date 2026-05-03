import duckdb
import sqlite3
import os

# =============================================================================
# SQLite(opendart.sqlite)의 표준화된 재무 데이터를
# DuckDB(analytics.duckdb)로 옮겨 mart_financial_base를 생성하는 스크립트
#
# 전제:
# - fact_financial_statement.account_std 가 이미 채워져 있음
#   (08_1_account_standardize_all.py 실행 완료)
#
# 결과:
# - DuckDB: mart_financial_base
#   -> 이후 모든 mart/analysis 단계의 "단일 원천 테이블"
# =============================================================================

SQLITE_PATH = "data/opendart.sqlite"
DUCKDB_PATH = "data/analytics.duckdb"

# -----------------------------------------------------------------------------
# DuckDB 연결
# -----------------------------------------------------------------------------
con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")

# SQLite 첨부
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

print("▶ DuckDB mart_financial_base 생성 시작")

# -----------------------------------------------------------------------------
# 필수 테이블 확인 (SQLite)
# -----------------------------------------------------------------------------
tables = con.execute("""
SELECT name
FROM sdb.sqlite_master
WHERE type='table'
""").fetchall()
table_names = {t[0] for t in tables}

required = {"fact_financial_statement"}
missing = required - table_names
if missing:
    raise RuntimeError(f"❌ SQLite에 필수 테이블이 없습니다: {missing}")

# -----------------------------------------------------------------------------
# mart_financial_base 생성
# -----------------------------------------------------------------------------
con.execute("""
CREATE OR REPLACE TABLE mart_financial_base AS
SELECT
    corp_code,
    bsns_year,
    reprt_code,
    fs_div,
    sj_div,
    account_nm,
    account_std,
    amount
FROM sdb.fact_financial_statement
WHERE amount IS NOT NULL;
""")

# -----------------------------------------------------------------------------
# 기본 검증 출력
# -----------------------------------------------------------------------------
row_cnt = con.execute(
    "SELECT COUNT(*) FROM mart_financial_base"
).fetchone()[0]

corp_cnt = con.execute(
    "SELECT COUNT(DISTINCT corp_code) FROM mart_financial_base"
).fetchone()[0]

year_min, year_max = con.execute(
    "SELECT MIN(bsns_year), MAX(bsns_year) FROM mart_financial_base"
).fetchone()

print("✅ mart_financial_base 생성 완료")
print(f"   총 행 수      : {row_cnt:,}")
print(f"   기업 수       : {corp_cnt:,}")
print(f"   연도 범위     : {year_min} ~ {year_max}")

con.close()

print("\n👉 다음 실행:")
print("   python scripts/08_3_rebuild_cash_mart_industry_auto_universal.py")