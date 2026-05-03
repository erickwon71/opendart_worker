import re
import sqlite3
import duckdb
from collections import defaultdict

# =============================================================================
# 목적
# - DuckDB(mart_financial_base)에서 실제로 많이 등장하는 account_nm을 자동 탐색해
#   SQLite(dim_account_mapping)에 매출/영업이익/자본총계(+필수 보조계정) 패턴을 영구 보강
#
# 왜 필요한가?
# - 회사마다 계정명이 다르고 표준계정(account_std)도 여러 이름으로 들어갈 수 있음
# - metrics(ROE/OPM)를 계산하려면 매출/영업이익/자본총계 등이 안정적으로 매핑되어야 함
#
# 입력
# - DuckDB: data/analytics.duckdb (mart_financial_base 존재)
# - SQLite: data/opendart.sqlite (dim_account_mapping 존재)
#
# 출력
# - SQLite: dim_account_mapping에 LIKE 규칙 추가(중복 방지)
#
# 실행 순서(중요)
# 1) python scripts/08_1d_strengthen_metric_mappings_from_data.py
# 2) python scripts/08_1_account_standardize_all.py
# 3) python scripts/08_2_build_duckdb_mart.py
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

# 상위 몇 개 account_nm까지 규칙으로 만들지(너무 많으면 과매칭 위험)
TOP_N_PER_METRIC = 25

# metric -> sj_div(재무제표 구분) & 키워드
# sj_div: IS(손익), BS(재무상태), CF(현금흐름)
METRIC_SPECS = {
    # ---- metrics 핵심 3개(요청사항) ----
    "매출액": {
        "sj_div": ["IS"],
        "keywords": ["매출", "수익", "영업수익", "Revenue", "Sales"]
    },
    "영업이익": {
        "sj_div": ["IS"],
        "keywords": ["영업이익", "영업이익(손실)", "Operating", "OPERATION"]
    },
    "자본총계": {
        "sj_div": ["BS"],
        "keywords": ["자본총계", "총자본", "자기자본", "Equity"]
    },

    # ---- (권장) ROE/부채비율 계산 안정화를 위한 보조계정 ----
    "자산총계": {
        "sj_div": ["BS"],
        "keywords": ["자산총계", "총자산", "Assets"]
    },
    "부채총계": {
        "sj_div": ["BS"],
        "keywords": ["부채총계", "총부채", "Liabilities"]
    },

    # ---- (권장) 현금/버핏쪽 안정화를 위한 보조계정(이미 있을 수 있음) ----
    "당기순이익": {
        "sj_div": ["IS"],
        "keywords": ["당기순이익", "순이익", "Net Income"]
    },
    "영업활동현금흐름": {
        "sj_div": ["CF"],
        "keywords": ["영업활동", "현금흐름", "Operating Cash Flow"]
    },
    "감가상각비": {
        "sj_div": ["CF", "IS"],
        "keywords": ["감가상각", "상각", "Depreciation", "Amortization"]
    },
}

def normalize_name(s: str) -> str:
    # 괄호/특수문자 정리, 연속 공백 제거
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def like_pattern_from_name(name: str) -> str:
    """
    계정명 name을 LIKE 패턴으로 변환:
    - 공백/구분문자를 토큰화한 뒤 "%토큰1%토큰2%..." 형태로 만들어 변형(공백/붙임) 모두 잡음
    """
    cleaned = re.sub(r"[\(\)\[\]\{\},\.\-_/]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = [t for t in cleaned.split(" ") if t]
    if not tokens:
        return f"%{name}%"
    # 토큰을 %로 연결하면 띄어쓰기/붙임 변형을 흡수 가능
    return "%" + "%".join(tokens) + "%"

def ensure_dim_account_mapping(conn_sqlite):
    cur = conn_sqlite.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dim_account_mapping (
        account_std TEXT NOT NULL,
        match_type  TEXT NOT NULL,
        pattern     TEXT NOT NULL
    );
    """)
    conn_sqlite.commit()

def insert_rule(conn_sqlite, account_std, match_type, pattern):
    cur = conn_sqlite.cursor()
    cur.execute("""
    INSERT INTO dim_account_mapping (account_std, match_type, pattern)
    SELECT ?, ?, ?
    WHERE NOT EXISTS (
      SELECT 1 FROM dim_account_mapping
      WHERE account_std=? AND match_type=? AND pattern=?
    );
    """, (account_std, match_type, pattern, account_std, match_type, pattern))
    conn_sqlite.commit()
    return cur.rowcount

# ------------------ DuckDB에서 후보 account_nm 추출 ------------------
con_duck = duckdb.connect(DUCKDB_PATH)

# 존재 확인
exists = con_duck.execute("""
SELECT COUNT(*) FROM information_schema.tables WHERE table_name='mart_financial_base'
""").fetchone()[0]
if exists == 0:
    con_duck.close()
    raise SystemExit("❌ DuckDB에 mart_financial_base가 없습니다. 먼저 08_2_build_duckdb_mart.py 실행하세요.")

# metric별 후보 추출
candidates = defaultdict(list)

for std_name, spec in METRIC_SPECS.items():
    sj_list = spec["sj_div"]
    kws = spec["keywords"]

    # sj_div 조건
    sj_cond = "(" + ",".join([f"'{x}'" for x in sj_list]) + ")"

    # keyword OR 조건 (LIKE)
    # DuckDB는 ILIKE 지원 (대소문자 무시)
    like_ors = " OR ".join([f"account_nm ILIKE '%{kw}%'" for kw in kws])

    query = f"""
    SELECT account_nm, COUNT(*) AS cnt
    FROM mart_financial_base
    WHERE reprt_code='11011'
      AND sj_div IN {sj_cond}
      AND account_nm IS NOT NULL
      AND ({like_ors})
    GROUP BY account_nm
    ORDER BY cnt DESC
    LIMIT {TOP_N_PER_METRIC}
    """

    rows = con_duck.execute(query).fetchall()
    # rows: [(account_nm, cnt), ...]
    for nm, cnt in rows:
        nm = normalize_name(nm)
        candidates[std_name].append((nm, cnt))

con_duck.close()

# ------------------ SQLite에 규칙 삽입 ------------------
conn_sqlite = sqlite3.connect(SQLITE_PATH)
ensure_dim_account_mapping(conn_sqlite)

inserted_total = 0

print("▶ 자동 탐색 기반 dim_account_mapping 보강 시작")
for std_name, rows in candidates.items():
    if not rows:
        print(f" - {std_name}: 후보 없음(스킵)")
        continue

    inserted = 0
    for nm, cnt in rows:
        pattern = like_pattern_from_name(nm)
        inserted += insert_rule(conn_sqlite, std_name, "LIKE", pattern)

    inserted_total += inserted
    top_preview = ", ".join([f"{r[0]}({r[1]})" for r in rows[:5]])
    print(f" - {std_name}: 후보 {len(rows)}개, 신규 규칙 {inserted}개 추가 | top: {top_preview}")

conn_sqlite.close()

print("\n✅ dim_account_mapping 보강 완료")
print(f"   총 신규 규칙 추가 수: {inserted_total}")
print("\n👉 다음 실행(반드시):")
print("   python scripts/08_1_account_standardize_all.py")
print("   python scripts/08_2_build_duckdb_mart.py")