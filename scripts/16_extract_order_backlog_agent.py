import sqlite3
import json
import duckdb
import re

# --------------------------------------------------
# 설정
# --------------------------------------------------
DB_PATH = "data/opendart.sqlite"
DUCKDB_PATH = "data/analytics.duckdb"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mart_order_backlog (
        corp_code TEXT,
        rcept_no TEXT,
        bsns_year INTEGER,
        total_order_amt REAL,   -- 수주총액
        completed_amt REAL,     -- 기납품액
        backlog_amt REAL,       -- 수주잔고
        updated_at TEXT,
        PRIMARY KEY (corp_code, bsns_year)
    )
    """)
    conn.commit()
    conn.close()

def get_backlog_candidates():
    # 텍스트 내에 수주 관련 키워드가 있는 보고서 탐색
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 상위 기업 중 수주 관련 키워드가 있는 경우
    cur.execute("""
    SELECT DISTINCT f.corp_code, dc.corp_name, b.rcept_no, f.rcept_dt, b.business_content_txt
    FROM fact_report_business_content b
    JOIN fact_filing f ON b.rcept_no = f.rcept_no
    JOIN dim_company dc ON f.corp_code = dc.corp_code
    WHERE (b.business_content_txt LIKE '%수주현황%' 
       OR b.business_content_txt LIKE '%수주잔고%'
       OR b.business_content_txt LIKE '%수주상황%')
      AND b.rcept_no NOT IN (SELECT rcept_no FROM mart_order_backlog)
    LIMIT 20
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def extract_backlog_context(text):
    # "수주" 키워드 주변 3000자 추출 (표가 포함될 확률 높음)
    match = re.search(r"(수주현황|수주잔고|수주상황)", text)
    if not match: return text[:3000]
    start = max(0, match.start() - 500)
    return text[start:start + 4000]

def save_backlog(corp_code, rcept_no, year, data):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO mart_order_backlog 
    (corp_code, rcept_no, bsns_year, total_order_amt, completed_amt, backlog_amt, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (corp_code, rcept_no, year, data.get('total'), data.get('completed'), data.get('backlog')))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    candidates = get_backlog_candidates()
    print(f"🔹 수주 잔고 분석 대상: {len(candidates)}개 기업")
    
    # 여기서부터는 서브 에이전트에게 위임하여 실제 수치 추출
