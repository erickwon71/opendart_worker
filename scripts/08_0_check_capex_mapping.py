import sqlite3
import argparse
from collections import Counter

DB_PATH = "data/opendart.sqlite"

parser = argparse.ArgumentParser()
parser.add_argument("--corp_code", type=str, default=None, help="특정 기업 capex_total 연도별 확인용 (예: 00126380)")
parser.add_argument("--fs_div", type=str, default="CFS", choices=["CFS","OFS"], help="재무구분")
args = parser.parse_args()

def q(cur, sql, params=None):
    cur.execute(sql, params or [])
    return cur.fetchall()

def exists_table(cur, name):
    rows = q(cur, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", [name])
    return len(rows) > 0

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("\n================ CAPEX 매핑 상태 점검 시작 ================\n")

# ---------------------------------------------------------
# 0) 테이블 존재 체크
# ---------------------------------------------------------
required_tables = [
    "fact_financial_statement",
    "dim_account_mapping",
    "stg_financial_std",
]
missing = [t for t in required_tables if not exists_table(cur, t)]
if missing:
    print("❌ 필수 테이블이 없습니다:", ", ".join(missing))
    print("   → 먼저 STEP 8-1 표준화 스크립트를 실행했는지 확인하세요.")
    conn.close()
    raise SystemExit(1)

print("✅ 필수 테이블 존재 확인 완료")

# ---------------------------------------------------------
# 1) 원본에 CAPEX 후보 계정이 존재하는가? (CF에서 유형/무형자산 관련)
# ---------------------------------------------------------
print("\n[1] 원본(fact_financial_statement) CAPEX 후보 계정 존재 여부")

rows = q(cur, """
SELECT account_nm, COUNT(*) AS cnt
FROM fact_financial_statement
WHERE sj_div='CF'
  AND account_nm IS NOT NULL
  AND (account_nm LIKE '%유형자산%' OR account_nm LIKE '%무형자산%')
GROUP BY account_nm
ORDER BY cnt DESC
LIMIT 30
""")

if not rows:
    print("❌ 원본(CF)에서 유형/무형자산 관련 계정이 하나도 발견되지 않았습니다.")
    print("   → (드물지만) 수집 범위/계정명/데이터 자체를 확인해야 합니다.")
else:
    print(f"✅ 원본에서 후보 계정 {len(rows)}개(상위 30) 발견")
    for acc, cnt in rows[:10]:
        print(f"  {cnt:10,} | {acc}")

# ---------------------------------------------------------
# 2) dim_account_mapping에 CAPEX 룰이 등록돼 있는가?
# ---------------------------------------------------------
print("\n[2] dim_account_mapping CAPEX 룰 등록 여부")

rules = q(cur, """
SELECT account_std, match_type, pattern
FROM dim_account_mapping
WHERE account_std LIKE 'CAPEX%'
ORDER BY account_std, pattern
""")

if not rules:
    print("❌ CAPEX 매핑 룰이 없습니다.")
    print("   → 08_1_account_standardize_all.py의 account_rules에 아래를 추가하세요:")
    print("      ('CAPEX_유형자산', 'LIKE', '%유형자산%취득%'),")
    print("      ('CAPEX_무형자산', 'LIKE', '%무형자산%취득%'),")
else:
    print(f"✅ CAPEX 매핑 룰 {len(rules)}개 존재")
    for r in rules:
        print("  -", r)

# ---------------------------------------------------------
# 3) 표준화(stg_financial_std)에 CAPEX가 실제로 내려왔는가?
# ---------------------------------------------------------
print("\n[3] stg_financial_std에 CAPEX 데이터 존재 여부")

std_rows = q(cur, """
SELECT account_std, COUNT(*) AS cnt
FROM stg_financial_std
WHERE account_std LIKE 'CAPEX%'
GROUP BY account_std
ORDER BY cnt DESC
""")

if not std_rows:
    print("❌ 표준화 테이블에 CAPEX 데이터가 없습니다.")
    print("   → 매핑 룰이 실제 계정명과 맞지 않거나, 08-1 재실행이 안 된 상태입니다.")
    print("   → 해결 순서:")
    print("      1) scripts/08_1_candidate_account_patterns.py 실행해서 실제 계정명 확인")
    print("      2) account_rules에 패턴 추가/수정")
    print("      3) python scripts/08_1_account_standardize_all.py 재실행")
else:
    print("✅ 표준화 테이블에 CAPEX 데이터 존재")
    for acc, cnt in std_rows:
        print(f"  {cnt:10,} | {acc}")

# ---------------------------------------------------------
# 4) (가능하면) DuckDB Mart 생성 여부는 SQLite에서 직접 확인 불가
#    대신, mart_buffett_cash_annual은 DuckDB에 있으므로 여기서는 '존재하지 않음'을 명확히 안내
# ---------------------------------------------------------
print("\n[4] mart_buffett_cash_annual (DuckDB) 점검 안내")
print("   - mart_buffett_cash_annual은 DuckDB(data/analytics.duckdb)에 존재합니다.")
print("   - SQLite에서는 직접 조회할 수 없으므로, 아래 'DuckDB 점검 스크립트'를 같이 제공합니다.\n")

conn.close()

# ---------------------------------------------------------
# 5) DuckDB 점검 스크립트 출력 안내
# ---------------------------------------------------------
print("===========================================================")
print("다음으로 DuckDB에서 capex_total이 실제로 들어갔는지 확인하려면")
print("아래 스크립트를 만들어 실행하세요: scripts/08_0_check_capex_duckdb.py")
print("===========================================================\n")