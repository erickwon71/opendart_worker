import duckdb

# =============================================================================
# 연도별 종합 점수 테이블 생성 (Yearly Scores)
#
# 목적:
# - 매 연도별로 Quality / Buffett / Combined Score 생성
# - Top20 선별 및 HTML 리포트의 기준 데이터 제공
#
# 입력:
# - mart_metrics_annual              (재무비율: roe, opm 등)
# - mart_buffett_cash_annual        (현금흐름: owner_earnings, fcf 등)
# - mart_buffett_earning_power_10y  (장기 Earning Power Score)
#
# 출력:
# - mart_score_combined_yearly
# - mart_score_combined_annual (최신 연도 only)
#
# 설계 원칙:
# - 점수는 연도별 상대 평가(NTILE)
# - 파생계산은 SELECT 내에서만 수행
# - 결측치는 점수 계산 대상에서 자동 제외
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"

con = duckdb.connect(DUCKDB_PATH)

print("▶ 연도별 종합 점수(yearly scores) 생성 시작")

# -----------------------------------------------------------------------------
# 필수 테이블 확인
# -----------------------------------------------------------------------------
required = [
    "mart_metrics_annual",
    "mart_buffett_cash_annual",
    "mart_buffett_earning_power_10y"
]

for t in required:
    exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [t]
    ).fetchone()[0]
    if exists == 0:
        con.close()
        raise SystemExit(f"❌ 필수 테이블이 없습니다: {t}")

# -----------------------------------------------------------------------------
# 1) 연도별 Quality / Buffett Score 계산
# -----------------------------------------------------------------------------
con.execute("""
CREATE OR REPLACE TABLE mart_score_combined_yearly AS
WITH base AS (
  SELECT
    m.corp_code,
    m.fs_div,
    m.bsns_year,

    -- Quality 지표
    m.roe,
    m.opm,

    -- Buffett 지표
    c.owner_earnings,
    c.free_cash_flow,

    CASE
      WHEN c.revenue IS NOT NULL AND c.revenue != 0
      THEN c.free_cash_flow / c.revenue
    END AS fcf_margin,

    CASE
      WHEN c.revenue IS NOT NULL AND c.revenue != 0
      THEN c.capex_total / c.revenue
    END AS capex_intensity,

    ep.earning_power_score

  FROM mart_metrics_annual m
  LEFT JOIN mart_buffett_cash_annual c
    ON m.corp_code = c.corp_code
   AND m.fs_div   = c.fs_div
   AND m.bsns_year = c.bsns_year
  LEFT JOIN mart_buffett_earning_power_10y ep
    ON m.corp_code = ep.corp_code
   AND m.fs_div   = ep.fs_div
),

scored AS (
  SELECT
    *,

    -- Quality Score (연도별 상대평가)
    6 - NTILE(5) OVER (PARTITION BY bsns_year ORDER BY roe DESC) AS score_roe,
    6 - NTILE(5) OVER (PARTITION BY bsns_year ORDER BY opm DESC) AS score_opm,

    -- Buffett Score (연도별 상대평가)
    6 - NTILE(5) OVER (PARTITION BY bsns_year ORDER BY owner_earnings DESC)
      AS score_owner_earnings,

    6 - NTILE(5) OVER (PARTITION BY bsns_year ORDER BY fcf_margin DESC)
      AS score_fcf_margin,

    NTILE(5) OVER (PARTITION BY bsns_year ORDER BY capex_intensity ASC)
      AS score_capex_light

  FROM base
  WHERE roe IS NOT NULL
    AND opm IS NOT NULL
    AND owner_earnings IS NOT NULL
)

SELECT
  corp_code,
  fs_div,
  bsns_year,

  -- Quality
  (score_roe + score_opm) AS total_score,

  -- Buffett
  (score_owner_earnings + score_fcf_margin + score_capex_light)
    AS buffett_total_score,

  -- Combined (0~1 스케일)
  (
    (score_roe + score_opm) +
    (score_owner_earnings + score_fcf_margin + score_capex_light)
  )::DOUBLE / 25.0 AS combined_score,

  earning_power_score

FROM scored;
""")

# -----------------------------------------------------------------------------
# 2) 최신 연도 Top Score 테이블 생성 (annual)
# -----------------------------------------------------------------------------
latest_year = con.execute(
    "SELECT MAX(bsns_year) FROM mart_score_combined_yearly"
).fetchone()[0]

con.execute("""
CREATE OR REPLACE TABLE mart_score_combined_annual AS
SELECT
  corp_code,
  fs_div,
  bsns_year AS year,
  total_score,
  buffett_total_score,
  combined_score,
  earning_power_score
FROM mart_score_combined_yearly
WHERE bsns_year = ?
""", [latest_year])

# -----------------------------------------------------------------------------
# 결과 요약 출력
# -----------------------------------------------------------------------------
cnt_all = con.execute(
    "SELECT COUNT(*) FROM mart_score_combined_yearly"
).fetchone()[0]

cnt_latest = con.execute(
    "SELECT COUNT(*) FROM mart_score_combined_annual"
).fetchone()[0]

print("✅ mart_score_combined_yearly 생성 완료")
print(f"   전체 행 수 : {cnt_all:,}")
print(f"✅ mart_score_combined_annual 생성 완료")
print(f"   {latest_year}년 기준 행 수 : {cnt_latest:,}")

con.close()

print("\n👉 다음 실행:")
print("   python scripts/10_3_batch_top20_html_reports.py")