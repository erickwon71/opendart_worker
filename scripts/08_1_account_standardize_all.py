import sqlite3

# =============================================================================
# 재무 계정 표준화 스크립트 (ALL)
#
# 목적:
# - fact_financial_statement.account_nm 을 표준계정(account_std)으로 매핑
# - dim_account_mapping에 정의된 규칙을 기반으로 일괄 적용
#
# 정책:
# - SQLite 전용 (opendart.sqlite)
# - 기존 account_std 값은 덮어쓰지 않음 (NULL인 경우만 채움)
# - LIKE 매칭만 사용 (현 구조 기준)
# =============================================================================

DB_PATH = "data/opendart.sqlite"

# ---------------------------------------------------------------------
# DB 연결
# ---------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ---------------------------------------------------------------------
# 필수 테이블 존재 확인
# ---------------------------------------------------------------------
required_tables = ["fact_financial_statement", "dim_account_mapping"]
for tbl in required_tables:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tbl,)
    )
    if cur.fetchone() is None:
        conn.close()
        raise SystemExit(f"❌ 필수 테이블이 없습니다: {tbl}")

# ---------------------------------------------------------------------
# 표준계정 컬럼(account_std) 확인
# ---------------------------------------------------------------------
cur.execute("PRAGMA table_info(fact_financial_statement)")
cols = [r[1] for r in cur.fetchall()]
if "account_std" not in cols:
    cur.execute(
        "ALTER TABLE fact_financial_statement ADD COLUMN account_std TEXT"
    )
    conn.commit()
    print("✅ fact_financial_statement.account_std 컬럼 추가 완료")

# ---------------------------------------------------------------------
# 표준화 수행
# - dim_account_mapping의 규칙을 순회하며
# - account_std IS NULL 인 레코드만 업데이트
# ---------------------------------------------------------------------
cur.execute("""
SELECT account_std, match_type, pattern
FROM dim_account_mapping
""")
rules = cur.fetchall()

total_updated = 0

for account_std, match_type, pattern in rules:
    if match_type != "LIKE":
        continue  # 현재 정책상 LIKE만 사용

    cur.execute("""
    UPDATE fact_financial_statement
    SET account_std = ?
    WHERE account_std IS NULL
      AND account_nm LIKE ?
    """, (account_std, pattern))

    updated = cur.rowcount
    if updated > 0:
        total_updated += updated

conn.commit()
conn.close()

print("✅ 계정 표준화(account_std) 완료")
print(f"   업데이트된 행 수: {total_updated:,}")
print("👉 다음 실행:")
print("   python scripts/08_2_build_duckdb_mart.py")
