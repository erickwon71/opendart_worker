import duckdb

# =============================================================================
# 5~10년 기준 Buffett Earning Power 요약 테이블 생성
#
# 입력:
#   - mart_buffett_cash_annual
#       * owner_earnings
#       * free_cash_flow
#       * capex_total
#       * revenue
#       * cfo
#       * net_income
#   - mart_metrics_annual (roe, opm)
#
# 출력:
#   - mart_buffett_earning_power_10y
#
# 핵심 원칙:
#   - 파생 비율은 "컬럼 참조"가 아니라 SELECT 내 계산식
#   - 5년 미만 데이터 기업은 제외
#   - 최근 10년 중 사용 가능한 연도만 집계
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"

# -----------------------------------------------------------------------------
# DuckDB 연결
# -----------------------------------------------------------------------------
con = duckdb.connect(DUCKDB_PATH)

print("▶ 5~10년 Buffett Earning Power Mart 생성 시작")

# -----------------------------------------------------------------------------
# 필수 테이블 확인
# -----------------------------------------------------------------------------
required_tables = [
    "mart_buffett_cash_annual",
    "mart_metrics_annual"
]

for tbl in required_tables:
    exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [tbl]
    ).fetchone()[0]
    if exists == 0:
        con.close()
        raise SystemExit(f"❌ 필수 테이블이 없습니다: {tbl}")

# -----------------------------------------------------------------------------
# Earning Power Mart 생성
# -----------------------------------------------------------------------------
con.execute("""
CREATE OR REPLACE TABLE mart_buffett_earning_power_10y AS
WITH base AS (
  SELECT
    cash.corp_code,
    cash.fs_div,
    cash.bsns_year,

    cash.owner_earnings,
    cash.free_cash_flow,

    -- 파생 비율 (컬럼 가정 금지)
    CASE
      WHEN cash.revenue IS NOT NULL AND cash.revenue != 0
      THEN cash.free_cash_flow / cash.revenue
    END AS fcf_margin,

    CASE
      WHEN cash.revenue IS NOT NULL AND cash.revenue != 0
      THEN cash.capex_total / cash.revenue
    END AS capex_intensity,

    CASE
      WHEN cash.net_income IS NOT NULL AND cash.net_income != 0
      THEN cash.cfo / cash.net_income
    END AS cash_conversion,

    m.roe,
    m.opm

  FROM mart_buffett_cash_annual cash
  LEFT JOIN mart_metrics_annual m
    ON cash.corp_code = m.corp_code
   AND cash.fs_div   = m.fs_div
   AND cash.bsns_year = m.bsns_year
),

-- 최소 5년 이상 데이터 기업만
eligible AS (
  SELECT corp_code, fs_div
  FROM base
  GROUP BY corp_code, fs_div
  HAVING COUNT(*) >= 5
),

-- 최근 연도 기준 정렬
windowed AS (
  SELECT
    b.*,
    ROW_NUMBER() OVER (
      PARTITION BY b.corp_code, b.fs_div
      ORDER BY b.bsns_year DESC
    ) AS rn
  FROM base b
  JOIN eligible e
    ON b.corp_code = e.corp_code
   AND b.fs_div   = e.fs_div
),

-- 최근 최대 10년 사용
sliced AS (
  SELECT *
  FROM windowed
  WHERE rn <= 10
),

-- 요약 집계
agg AS (
  SELECT
    corp_code,
    fs_div,

    MIN(bsns_year) AS start_year,
    MAX(bsns_year) AS end_year,
    COUNT(*)       AS years_used,

    AVG(owner_earnings)   AS avg_owner_earnings,
    AVG(free_cash_flow)   AS avg_fcf,
    AVG(fcf_margin)       AS avg_fcf_margin,
    AVG(capex_intensity)  AS avg_capex_intensity,
    AVG(cash_conversion)  AS avg_cash_conversion,

    SUM(CASE WHEN owner_earnings > 0 THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)
      AS positive_owner_ratio,

    AVG(roe)          AS avg_roe,
    STDDEV_POP(roe)   AS std_roe,
    AVG(opm)          AS avg_opm,
    STDDEV_POP(opm)   AS std_opm

  FROM sliced
  GROUP BY corp_code, fs_div
),

-- 점수화
scored AS (
  SELECT
    *,

    6 - NTILE(5) OVER (ORDER BY positive_owner_ratio DESC)
      AS score_owner_stability,

    6 - NTILE(5) OVER (ORDER BY avg_owner_earnings DESC)
      AS score_owner_level,

    6 - NTILE(5) OVER (ORDER BY avg_fcf_margin DESC)
      AS score_fcf,

    6 - NTILE(5) OVER (ORDER BY avg_cash_conversion DESC)
      AS score_cash_quality,

    NTILE(5) OVER (ORDER BY avg_capex_intensity ASC)
      AS score_capex_light,

    NTILE(5) OVER (ORDER BY std_roe ASC)
      AS score_moat_stability

  FROM agg
)

SELECT
  *,

  (
    score_owner_stability +
    score_owner_level +
    score_fcf +
    score_cash_quality +
    score_capex_light +
    score_moat_stability
  ) AS earning_power_score

FROM scored;
""")

# -----------------------------------------------------------------------------
# 결과 요약 출력
# -----------------------------------------------------------------------------
row_cnt = con.execute(
    "SELECT COUNT(*) FROM mart_buffett_earning_power_10y"
).fetchone()[0]

corp_cnt = con.execute(
    "SELECT COUNT(DISTINCT corp_code) FROM mart_buffett_earning_power_10y"
).fetchone()[0]

print("✅ mart_buffett_earning_power_10y 생성 완료")
print(f"   요약 행 수 : {row_cnt:,}")
print(f"   기업 수   : {corp_cnt:,}")

con.close()

print("\n👉 다음 실행:")
print("   python scripts/09_6_build_yearly_scores.py")
print("   python scripts/10_3_batch_top20_html_reports.py")