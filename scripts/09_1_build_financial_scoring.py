import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 9 재무 스크리닝 결과 상세 조회")

# SQLite(dim_company) 붙이기
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# -------------------------------------------------
# 1) 컬럼(제목) 설명 출력
# -------------------------------------------------
print("\n[테이블: mart_score_annual 컬럼 설명]")
columns = [
    ("corp_code", "DART 기업 고유코드"),
    ("corp_name", "기업명"),
    ("bsns_year", "사업연도"),
    ("fs_div", "재무구분(CFS=연결, OFS=별도)"),
    ("roe", "ROE (자기자본이익률)"),
    ("opm", "영업이익률"),
    ("debt_ratio", "부채비율"),
    ("yoy_revenue", "매출액 전년 대비 성장률"),
    ("yoy_net_income", "순이익 전년 대비 성장률"),
    ("score_roe", "ROE 점수(1~5)"),
    ("score_opm", "영업이익률 점수"),
    ("score_debt", "부채비율 점수"),
    ("score_yoy_rev", "매출 성장 점수"),
    ("score_yoy_ni", "순이익 성장 점수"),
    ("total_score", "최종 재무 스크리닝 점수")
]

for c, desc in columns:
    print(f"- {c:15} : {desc}")

# -------------------------------------------------
# 2) TOP 20 결과 출력 (기업명 포함)
# -------------------------------------------------
print("\n[TOP 20 재무 스크리닝 결과]\n")

rows = con.execute("""
SELECT
  m.corp_code,
  dc.corp_name,
  m.bsns_year,
  m.fs_div,
  ROUND(m.roe, 3) AS roe,
  ROUND(m.opm, 3) AS opm,
  ROUND(m.debt_ratio, 3) AS debt_ratio,
  ROUND(m.yoy_revenue, 3) AS yoy_revenue,
  ROUND(m.yoy_net_income, 3) AS yoy_net_income,
  m.score_roe,
  m.score_opm,
  m.score_debt,
  m.score_yoy_rev,
  m.score_yoy_ni,
  m.total_score
FROM mart_score_annual m
LEFT JOIN sdb.dim_company dc
  ON m.corp_code = dc.corp_code
ORDER BY m.total_score DESC
LIMIT 20;
""").fetchall()

for r in rows:
    print(r)

con.close()