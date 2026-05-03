import os
import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"
OUTPUT_DIR = "output"
OUTPUT_FILE = "step9_combined_score_latest.csv"

# 가중치(원하면 여기만 바꾸면 됨)
W_QUALITY = 0.5   # 기존 재무점수(mart_score_annual)
W_BUFFETT = 0.5   # 버핏형 현금/Owner Earnings 점수

os.makedirs(OUTPUT_DIR, exist_ok=True)

con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 9-C 기존 점수 + 버핏형 점수 결합 시작")

# SQLite(기업명) 붙이기
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# 최신 연도 자동 선택 (둘 중 더 최신을 사용)
latest_year = con.execute("""
SELECT GREATEST(
  (SELECT COALESCE(MAX(bsns_year),0) FROM mart_score_annual),
  (SELECT COALESCE(MAX(bsns_year),0) FROM mart_buffett_owner_score_annual)
)
""").fetchone()[0]

print(f"▶ 결합 기준 연도: {latest_year}")
print(f"▶ 가중치: QUALITY={W_QUALITY}, BUFFETT={W_BUFFETT}")

# 결합 테이블 생성
con.execute(f"""
CREATE OR REPLACE TABLE mart_score_combined_annual AS
WITH q AS (
  SELECT
    corp_code, bsns_year, fs_div,
    total_score,
    roe, opm, debt_ratio, yoy_revenue, yoy_net_income
  FROM mart_score_annual
  WHERE bsns_year = {latest_year}
),
b AS (
  SELECT
    corp_code, bsns_year, fs_div,
    buffett_total_score,
    owner_earnings, free_cash_flow, fcf_margin, cash_conversion, capex_intensity
  FROM mart_buffett_owner_score_annual
  WHERE bsns_year = {latest_year}
),
joined AS (
  SELECT
    COALESCE(q.corp_code, b.corp_code) AS corp_code,
    COALESCE(q.bsns_year, b.bsns_year) AS bsns_year,
    COALESCE(q.fs_div, b.fs_div) AS fs_div,

    q.total_score,
    b.buffett_total_score,

    -- 기존 점수 부가 지표
    q.roe, q.opm, q.debt_ratio, q.yoy_revenue, q.yoy_net_income,

    -- 버핏 점수 부가 지표
    b.owner_earnings, b.free_cash_flow, b.fcf_margin, b.cash_conversion, b.capex_intensity
  FROM q
  FULL OUTER JOIN b
    ON q.corp_code = b.corp_code
   AND q.bsns_year = b.bsns_year
   AND q.fs_div = b.fs_div
),
norm AS (
  SELECT
    *,
    -- 0~1 정규화(최대값 기준)
    CASE WHEN total_score IS NOT NULL AND (SELECT MAX(total_score) FROM joined) > 0
         THEN total_score / (SELECT MAX(total_score) FROM joined)
    END AS norm_quality,

    CASE WHEN buffett_total_score IS NOT NULL AND (SELECT MAX(buffett_total_score) FROM joined) > 0
         THEN buffett_total_score / (SELECT MAX(buffett_total_score) FROM joined)
    END AS norm_buffett
  FROM joined
),
scored AS (
  SELECT
    *,
    ({W_QUALITY} * COALESCE(norm_quality, 0.0)
     + {W_BUFFETT} * COALESCE(norm_buffett, 0.0)) AS combined_score
  FROM norm
)
SELECT
  s.corp_code,
  dc.corp_name,
  s.bsns_year AS year,
  s.fs_div,

  -- 최종 점수
  ROUND(s.combined_score, 6) AS combined_score,

  -- 원점수(참고)
  s.total_score,
  s.buffett_total_score,

  -- 기존(quality) 구성 요소(참고)
  s.roe, s.opm, s.debt_ratio, s.yoy_revenue, s.yoy_net_income,

  -- 버핏(owner earnings) 구성 요소(참고)
  s.owner_earnings, s.free_cash_flow, s.fcf_margin, s.cash_conversion, s.capex_intensity
FROM scored s
LEFT JOIN sdb.dim_company dc
  ON s.corp_code = dc.corp_code
ORDER BY combined_score DESC;
""")

# TOP 20 출력
print("\n▶ 결합 점수 TOP 20")
top = con.execute("""
SELECT corp_code, corp_name, fs_div, combined_score, total_score, buffett_total_score
FROM mart_score_combined_annual
LIMIT 20;
""").fetchall()

for r in top:
    print(r)

# CSV Export
output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
con.execute(f"""
COPY (
  SELECT * FROM mart_score_combined_annual
)
TO '{output_path}'
WITH (HEADER, DELIMITER ',');
""")

print(f"\n✅ 결합 결과 CSV 저장 완료: {output_path}")

con.close()
