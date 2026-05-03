import duckdb

con = duckdb.connect("data/analytics.duckdb")

print("\n▶ 최근 연도 ROE 상위 20 (연결/별도 구분)")
rows = con.execute("""
SELECT corp_code, bsns_year, fs_div, roe, revenue, net_income
FROM mart_metrics_annual
WHERE roe IS NOT NULL
ORDER BY bsns_year DESC, roe DESC
LIMIT 20;
""").fetchall()

for r in rows:
    print(r)

con.close()