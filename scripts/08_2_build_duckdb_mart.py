import duckdb

SQLITE_PATH = "data/opendart.sqlite"
DUCKDB_PATH = "data/analytics.duckdb"

con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

print("▶ DuckDB mart 생성 시작 (financial_base + metrics + growth)")

# 1) mart_financial_base
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

# 2) mart_metrics_annual (사업보고서 11011 기준)
con.execute("""
CREATE OR REPLACE TABLE mart_metrics_annual AS
WITH base AS (
  SELECT *
  FROM mart_financial_base
  WHERE reprt_code = '11011'
),
wide AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,

    -- ✅ 매출 (account_nm 기반)
    MAX(CASE WHEN account_nm ILIKE '%매출%' OR account_nm ILIKE '%수익%' THEN amount END) AS revenue,

    -- ✅ 영업이익 (account_nm 기반)
    MAX(CASE WHEN account_nm ILIKE '%영업이익%' THEN amount END) AS op_income,

    -- ✅ 당기순이익 (account_nm 기반)
    MAX(CASE WHEN account_nm ILIKE '%당기순이익%' OR account_nm ILIKE '%순이익%' THEN amount END) AS net_income,

    -- ✅ 자산/부채/자본
    MAX(CASE WHEN account_nm ILIKE '%자산총계%' OR account_nm ILIKE '%총자산%' THEN amount END) AS assets,
    MAX(CASE WHEN account_nm ILIKE '%부채총계%' OR account_nm ILIKE '%총부채%' THEN amount END) AS liabilities,
    MAX(CASE WHEN account_nm ILIKE '%자본총계%' OR account_nm ILIKE '%자기자본%' THEN amount END) AS equity

  FROM base
  GROUP BY corp_code, bsns_year, fs_div
)
SELECT
  corp_code,
  bsns_year,
  fs_div,
  revenue,
  op_income,
  net_income,
  assets,
  liabilities,
  equity,
  CASE WHEN equity IS NOT NULL AND equity != 0 THEN net_income / equity END AS roe,
  CASE WHEN revenue IS NOT NULL AND revenue != 0 THEN op_income / revenue END AS opm,
  CASE WHEN assets IS NOT NULL AND assets != 0 THEN liabilities / assets END AS debt_ratio
FROM wide;
""")

# 3) mart_growth_annual (YoY)
con.execute("""
CREATE OR REPLACE TABLE mart_growth_annual AS
WITH m AS (
  SELECT corp_code, fs_div, bsns_year, revenue, op_income, net_income
  FROM mart_metrics_annual
),
lagged AS (
  SELECT
    corp_code,
    fs_div,
    bsns_year,
    revenue,
    op_income,
    net_income,
    LAG(revenue) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_revenue,
    LAG(op_income) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_op_income,
    LAG(net_income) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_net_income
  FROM m
)
SELECT
  corp_code,
  fs_div,
  bsns_year,
  revenue,
  op_income,
  net_income,
  CASE WHEN prev_revenue IS NOT NULL AND prev_revenue != 0
       THEN (revenue - prev_revenue) / prev_revenue END AS yoy_revenue,
  CASE WHEN prev_op_income IS NOT NULL AND prev_op_income != 0
       THEN (op_income - prev_op_income) / prev_op_income END AS yoy_op_income,
  CASE WHEN prev_net_income IS NOT NULL AND prev_net_income != 0
       THEN (net_income - prev_net_income) / prev_net_income END AS yoy_net_income
FROM lagged;
""")

# 요약 출력
b = con.execute("SELECT COUNT(*) FROM mart_financial_base").fetchone()[0]
m = con.execute("SELECT COUNT(*) FROM mart_metrics_annual").fetchone()[0]
g = con.execute("SELECT COUNT(*) FROM mart_growth_annual").fetchone()[0]
print("✅ DuckDB mart 생성 완료")
print(f"   mart_financial_base : {b:,} rows")
print(f"   mart_metrics_annual : {m:,} rows")
print(f"   mart_growth_annual  : {g:,} rows")

con.close()

print("\n👉 다음 실행:")
print("   python scripts/08_3_rebuild_cash_mart_industry_auto_universal.py")
print("   python scripts/08_4_build_buffett_earning_power_10y.py")
print("   python scripts/09_6_build_yearly_scores.py")
print("   python scripts/10_3_batch_top20_html_reports.py")