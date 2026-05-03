import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 9-B Buffett Owner Earnings 점수화 시작")

# -------------------------------------------------
# 1) 최신 연도 확인
# -------------------------------------------------
latest_year = con.execute("""
SELECT MAX(bsns_year) FROM mart_buffett_cash_annual
""").fetchone()[0]

print(f"▶ 점수화 기준 연도: {latest_year}")

# -------------------------------------------------
# 2) 버핏형 Owner Earnings 점수화
# -------------------------------------------------
con.execute("""
CREATE OR REPLACE TABLE mart_buffett_owner_score_annual AS
WITH base AS (
  SELECT
    c.corp_code,
    c.bsns_year,
    c.fs_div,

    c.owner_earnings,
    c.free_cash_flow,
    c.fcf_margin,
    c.capex_total,
    c.cfo,
    c.net_income,

    CASE
      WHEN c.net_income IS NOT NULL AND c.net_income != 0
      THEN c.cfo / c.net_income
    END AS cash_conversion,

    CASE
      WHEN c.revenue IS NOT NULL AND c.revenue != 0
      THEN c.capex_total / c.revenue
    END AS capex_intensity

  FROM mart_buffett_cash_annual c
  WHERE c.bsns_year = ?
),

scored AS (
  SELECT
    *,

    -- Owner Earnings 크기 (클수록 좋음)
    6 - NTILE(5) OVER (ORDER BY owner_earnings DESC NULLS LAST)
      AS score_owner_earnings,

    -- FCF 마진
    6 - NTILE(5) OVER (ORDER BY fcf_margin DESC NULLS LAST)
      AS score_fcf_margin,

    -- 현금 전환율 (CFO / 순이익)
    6 - NTILE(5) OVER (ORDER BY cash_conversion DESC NULLS LAST)
      AS score_cash_conversion,

    -- 자본집약도 (낮을수록 좋음)
    NTILE(5) OVER (ORDER BY capex_intensity ASC NULLS LAST)
      AS score_capex_intensity

  FROM base
)

SELECT
  corp_code,
  bsns_year,
  fs_div,

  owner_earnings,
  free_cash_flow,
  fcf_margin,
  cash_conversion,
  capex_intensity,

  score_owner_earnings,
  score_fcf_margin,
  score_cash_conversion,
  score_capex_intensity,

  ( score_owner_earnings
  + score_fcf_margin
  + score_cash_conversion
  + score_capex_intensity ) AS buffett_total_score

FROM scored;
""", [latest_year])

# -------------------------------------------------
# 3) 결과 확인
# -------------------------------------------------
cnt = con.execute("""
SELECT COUNT(*) FROM mart_buffett_owner_score_annual
""").fetchone()[0]

print(f"✅ Buffett Owner Score 생성 완료: {cnt:,}개 기업")

print("\n▶ Buffett Owner Earnings TOP 20")
rows = con.execute("""
SELECT corp_code, fs_div,
       buffett_total_score,
       owner_earnings,
       free_cash_flow,
       fcf_margin
FROM mart_buffett_owner_score_annual
ORDER BY buffett_total_score DESC
LIMIT 20
""").fetchall()

for r in rows:
    print(r)

con.close()