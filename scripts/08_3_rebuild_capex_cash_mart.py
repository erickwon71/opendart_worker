import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
con = duckdb.connect(DUCKDB_PATH)

print("▶ CAPEX 집계 Mart 재생성 (제조업 확장 버전)")

con.execute("""
CREATE OR REPLACE TABLE mart_buffett_cash_annual AS
WITH base AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,
    account_std,
    amount
  FROM mart_financial_base
  WHERE reprt_code = '11011'
),

agg AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,

    -- ✅ Strict CAPEX (기존 버핏 정의)
    SUM(CASE WHEN account_std IN ('CAPEX_유형자산','CAPEX_무형자산')
             THEN amount END) AS capex_strict,

    -- ✅ Broad CAPEX (제조업용 확장)
    SUM(CASE WHEN account_std IN (
        'CAPEX_유형자산',
        'CAPEX_무형자산',
        '유형자산_건설중',
        '설비투자',
        '기계장치취득'
      ) THEN amount END) AS capex_broad,

    SUM(CASE WHEN account_std='영업활동현금흐름' THEN amount END) AS cfo,
    SUM(CASE WHEN account_std='감가상각비' THEN amount END) AS depreciation,
    SUM(CASE WHEN account_std='당기순이익' THEN amount END) AS net_income,
    SUM(CASE WHEN account_std='매출액' THEN amount END) AS revenue

  FROM base
  GROUP BY corp_code, bsns_year, fs_div
)

SELECT
  corp_code,
  bsns_year,
  fs_div,

  cfo,
  net_income,
  depreciation,
  revenue,

  capex_strict,
  capex_broad,

  -- 기본 분석에 사용할 CAPEX는 broad로
  capex_broad AS capex_total,

  cfo - COALESCE(capex_broad,0) AS free_cash_flow,
  net_income + COALESCE(depreciation,0) - COALESCE(capex_broad,0) AS owner_earnings
FROM agg;
""")

con.close()
print("✅ 제조업 대응 CAPEX 집계 완료")