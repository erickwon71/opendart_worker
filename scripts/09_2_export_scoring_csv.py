import os
import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"
OUTPUT_DIR = "output"
OUTPUT_FILE = "step9_financial_screening_latest.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)

con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 9 재무 스크리닝 결과 CSV Export 시작")

# SQLite(dim_company) 연결
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# 최신 연도 확인
latest_year = con.execute("""
SELECT MAX(bsns_year) FROM mart_score_annual
""").fetchone()[0]

print(f"▶ Export 기준 연도: {latest_year}")

# CSV Export
output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)

con.execute(f"""
COPY (
  SELECT
    m.corp_code                               AS corp_code,
    dc.corp_name                             AS corp_name,
    m.bsns_year                              AS year,
    m.fs_div                                 AS fs_div,
    ROUND(m.roe, 4)                          AS roe,
    ROUND(m.opm, 4)                          AS opm,
    ROUND(m.debt_ratio, 4)                   AS debt_ratio,
    ROUND(m.yoy_revenue, 4)                  AS yoy_revenue,
    ROUND(m.yoy_net_income, 4)               AS yoy_net_income,
    m.score_roe,
    m.score_opm,
    m.score_debt,
    m.score_yoy_rev,
    m.score_yoy_ni,
    m.total_score
  FROM mart_score_annual m
  LEFT JOIN sdb.dim_company dc
    ON m.corp_code = dc.corp_code
  WHERE m.bsns_year = {latest_year}
  ORDER BY m.total_score DESC
)
TO '{output_path}'
WITH (HEADER, DELIMITER ',');
""")

con.close()

print(f"✅ CSV Export 완료")
print(f"📁 파일 위치: {output_path}")