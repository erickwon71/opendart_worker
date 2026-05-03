import duckdb
import os

SQLITE_PATH = "data/opendart.sqlite"
DUCKDB_PATH = "data/analytics.duckdb"

con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 8-3 Buffett Cash (FCF / Owner Earnings) Mart 생성 시작")

# SQLite 붙이기
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# -------------------------------------------------
# 1) 연간 현금 기반 Mart 생성
# -------------------------------------------------
# 사업보고서(11011) 기준, 연 단위 분석
con.execute("""
CREATE OR REPLACE TABLE mart_buffett_cash_annual AS
WITH base AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,
    account_std,
    SUM(amount) AS amount
  FROM mart_financial_base
  WHERE reprt_code = '11011'
    AND account_std IN (
      '영업활동현금흐름',
      'CAPEX_유형자산',
      'CAPEX_무형자산',
      '감가상각비',
      '당기순이익',
      '매출액'
    )
  GROUP BY 1,2,3,4
),
pivoted AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,
    MAX(CASE WHEN account_std='영업활동현금흐름' THEN amount END) AS cfo,
    MAX(CASE WHEN account_std='CAPEX_유형자산' THEN amount END) AS capex_ppe,
    MAX(CASE WHEN account_std='CAPEX_무형자산' THEN amount END) AS capex_int,
    MAX(CASE WHEN account_std='감가상각비' THEN amount END) AS depreciation,
    MAX(CASE WHEN account_std='당기순이익' THEN amount END) AS net_income,
    MAX(CASE WHEN account_std='매출액' THEN amount END) AS revenue
  FROM base
  GROUP BY corp_code, bsns_year, fs_div
)
SELECT
  corp_code,
  bsns_year,
  fs_div,
  cfo,
  capex_ppe,
  capex_int,
  (COALESCE(capex_ppe,0) + COALESCE(capex_int,0))              AS capex_total,
  net_income,
  depreciation,
  revenue,

  -- Free Cash Flow
  CASE
    WHEN cfo IS NOT NULL
    THEN cfo - (COALESCE(capex_ppe,0) + COALESCE(capex_int,0))
  END AS free_cash_flow,

  -- Owner Earnings (보수적 근사)
  CASE
    WHEN net_income IS NOT NULL
    THEN net_income
         + COALESCE(depreciation,0)
         - (COALESCE(capex_ppe,0) + COALESCE(capex_int,0))
  END AS owner_earnings,

  -- 보조 비율
  CASE
    WHEN revenue IS NOT NULL AND revenue != 0
    THEN (cfo - (COALESCE(capex_ppe,0) + COALESCE(capex_int,0))) / revenue
  END AS fcf_margin

FROM pivoted;
""")

# -------------------------------------------------
# 2) 간단 검증 출력
# -------------------------------------------------
cnt = con.execute("""
SELECT COUNT(*) FROM mart_buffett_cash_annual
""").fetchone()[0]

print(f"✅ mart_buffett_cash_annual 생성 완료: {cnt:,} rows")

print("\n▶ FCF 상위 10개 기업(최근 연도)")
rows = con.execute("""
SELECT corp_code, fs_div, bsns_year,
       owner_earnings, free_cash_flow, fcf_margin
FROM mart_buffett_cash_annual
WHERE free_cash_flow IS NOT NULL
ORDER BY bsns_year DESC, free_cash_flow DESC
LIMIT 10
""").fetchall()

for r in rows:
    print(r)

con.close()