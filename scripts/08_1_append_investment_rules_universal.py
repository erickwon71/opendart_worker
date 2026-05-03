import sqlite3

# =============================================================================
# 투자/현금흐름 계정 표준화 매핑(범용) 추가 스크립트
#
# 목적:
# - 업종에 관계없이 "투자 성격"으로 볼 수 있는 현금흐름 계정을
#   표준계정(INV_*)으로 폭넓게 매핑
# - 이후 단계(08_3)에서 업종별 자동 선택(CAPEX vs 비포함)을 가능하게 함
#
# 정책:
# - 기존 매핑은 건드리지 않음 (중복 INSERT 방지)
# - SQLite(opendart.sqlite)만 사용
#
# 사용 순서:
#   1) python scripts/08_1_append_investment_rules_universal.py
#   2) python scripts/08_1_account_standardize_all.py
#   3) python scripts/08_2_build_duckdb_mart.py
# =============================================================================

DB_PATH = "data/opendart.sqlite"

# -----------------------------------------------------------------------------
# 범용 투자/현금흐름 매핑 룰
# -----------------------------------------------------------------------------
# match_type:
#   - LIKE : account_nm에 대해 부분 문자열 매칭
#
# account_std:
#   - INV_* : 투자 성격 계정(운영/확장)
#   - CFO/NET_INCOME/DEPRECIATION/REVENUE : 핵심 지표
# -----------------------------------------------------------------------------
RULES = [
    # ---------------- 운영 CAPEX 후보 (Owner Earnings 차감 대상) ----------------
    ("INV_PPE_ACQ",        "LIKE", "%유형자산%취득%"),
    ("INV_INTANG_ACQ",     "LIKE", "%무형자산%취득%"),
    ("INV_CIP",            "LIKE", "%건설중%자산%"),
    ("INV_CIP",            "LIKE", "%건설 중%자산%"),
    ("INV_FACILITY",       "LIKE", "%설비%투자%"),
    ("INV_FACILITY",       "LIKE", "%시설%투자%"),
    ("INV_EQUIPMENT",      "LIKE", "%기계%취득%"),
    ("INV_EQUIPMENT",      "LIKE", "%장비%취득%"),
    ("INV_SOFTWARE",       "LIKE", "%소프트웨어%취득%"),
    ("INV_DEV_COST",       "LIKE", "%개발비%"),

    # ---------------- 확장 투자 후보 (참고/리포트용) ----------------
    ("INV_SUBSIDIARY_ACQ", "LIKE", "%종속기업%취득%"),
    ("INV_BUSINESS_ACQ",   "LIKE", "%사업%취득%"),
    ("INV_ASSOCIATE",      "LIKE", "%관계기업%취득%"),
    ("INV_EQUITY_INVEST",  "LIKE", "%지분%취득%"),
    ("INV_SECURITIES",     "LIKE", "%유가증권%취득%"),
    ("INV_FIN_ASSET",      "LIKE", "%금융자산%취득%"),
    ("INV_LOANS",          "LIKE", "%대여금%지급%"),

    # ---------------- 핵심 현금/이익/매출 ----------------
    ("CFO",                "LIKE", "%영업활동%현금%"),
    ("DEPRECIATION",       "LIKE", "%감가상각%"),
    ("NET_INCOME",         "LIKE", "%순이익%"),
    ("REVENUE",            "LIKE", "%매출%"),
]

# -----------------------------------------------------------------------------
# DB 연결
# -----------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# -----------------------------------------------------------------------------
# dim_account_mapping 테이블 확인/생성
# -----------------------------------------------------------------------------
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_account_mapping (
    account_std TEXT NOT NULL,
    match_type  TEXT NOT NULL,
    pattern     TEXT NOT NULL
);
""")

# -----------------------------------------------------------------------------
# 중복 방지 INSERT
# -----------------------------------------------------------------------------
insert_sql = """
INSERT INTO dim_account_mapping (account_std, match_type, pattern)
SELECT ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1
    FROM dim_account_mapping
    WHERE account_std = ?
      AND match_type  = ?
      AND pattern     = ?
);
"""

inserted = 0

for account_std, match_type, pattern in RULES:
    cur.execute(insert_sql, (
        account_std, match_type, pattern,
        account_std, match_type, pattern
    ))
    if cur.rowcount > 0:
        inserted += 1

conn.commit()
conn.close()

print("✅ 범용 투자/현금흐름 매핑 룰 추가 완료")
print(f"   새로 추가된 규칙 수: {inserted}")
print("👉 다음 실행:")
print("   python scripts/08_1_account_standardize_all.py")
print("   python scripts/08_2_build_duckdb_mart.py")