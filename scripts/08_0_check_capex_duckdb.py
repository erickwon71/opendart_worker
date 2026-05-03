import argparse
import duckdb

DUCKDB_PATH = "data/analytics.duckdb"

parser = argparse.ArgumentParser()
parser.add_argument("--corp_code", type=str, default=None, help="특정 기업 연도별 capex_total 확인")
parser.add_argument("--fs_div", type=str, default="CFS", choices=["CFS","OFS"])
args = parser.parse_args()

con = duckdb.connect(DUCKDB_PATH)

print("\n================ DuckDB CAPEX 점검 시작 ================\n")

# 1) 테이블 존재 확인
tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
if "mart_buffett_cash_annual" not in tables:
    print("❌ mart_buffett_cash_annual 테이블이 없습니다.")
    print("   → 먼저 python scripts/08_3_build_buffett_cash_mart.py 를 실행하세요.")
    con.close()
    raise SystemExit(1)

print("✅ mart_buffett_cash_annual 존재 확인")

# 2) capex_total 분포 확인 (NULL 비율)
row = con.execute("""
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN capex_total IS NULL THEN 1 ELSE 0 END) AS null_cnt,
  SUM(CASE WHEN capex_total IS NOT NULL THEN 1 ELSE 0 END) AS not_null_cnt
FROM mart_buffett_cash_annual
""").fetchone()

total, null_cnt, not_null_cnt = row
print(f"\n[1] capex_total 전체 분포")
print(f"  - total      : {total:,}")
print(f"  - null       : {null_cnt:,}")
print(f"  - not null   : {not_null_cnt:,}")

# 3) capex_total 상위 샘플 (절대값 큰 순)
print("\n[2] capex_total 샘플(절대값 큰 순) TOP 10")
rows = con.execute("""
SELECT corp_code, fs_div, bsns_year, capex_total, revenue, owner_earnings
FROM mart_buffett_cash_annual
WHERE capex_total IS NOT NULL
ORDER BY ABS(capex_total) DESC
LIMIT 10
""").fetchall()

for r in rows:
    print(r)

# 4) 특정 기업 연도별 확인
if args.corp_code:
    print(f"\n[3] 기업별 연도 capex_total 확인: {args.corp_code} / {args.fs_div}")
    rows = con.execute("""
    SELECT bsns_year, capex_total, owner_earnings, free_cash_flow
    FROM mart_buffett_cash_annual
    WHERE corp_code=? AND fs_div=?
    ORDER BY bsns_year
    """, [args.corp_code, args.fs_div]).fetchall()

    if not rows:
        print("  ❌ 해당 기업/재무구분 데이터가 없습니다.")
    else:
        for r in rows:
            print("  ", r)

con.close()
print("\n================ DuckDB CAPEX 점검 종료 ================\n")
