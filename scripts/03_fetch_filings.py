"""
03_fetch_filings.py

역할:
- OpenDART list.json으로 공시 목록(전일~오늘 기본) 증분 수집
- Raw JSON 저장(재처리/감사 목적)
- SQLite fact_filing에 INSERT OR IGNORE로 멱등 적재

참고: list.json 파라미터/응답 필드(총 페이지/리스트 구조 등)는 OpenDART 개발가이드 명세를 따른다. [1](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)

실행 예:
python scripts/03_fetch_filings.py
python scripts/03_fetch_filings.py --bgn_de 20260401 --end_de 20260429
"""

import os
import json
import argparse
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
import sqlite3

# -------------------------------
# 0) 날짜 유틸
# -------------------------------
def yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")

def default_range():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    return yyyymmdd(yesterday), yyyymmdd(today)

# -------------------------------
# 1) CLI 파라미터
# -------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--bgn_de", type=str, default=None, help="시작일(YYYYMMDD)")
parser.add_argument("--end_de", type=str, default=None, help="종료일(YYYYMMDD)")
parser.add_argument("--page_count", type=int, default=100, help="페이지당 건수(1~100)")
parser.add_argument("--last_reprt_at", type=str, default="N", help="최종보고서만(Y/N)")
args = parser.parse_args()

bgn_de, end_de = args.bgn_de, args.end_de
if not bgn_de or not end_de:
    bgn_de, end_de = default_range()

# -------------------------------
# 2) 환경 변수 로드
# -------------------------------
load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
if not API_KEY:
    raise RuntimeError("❌ DART_API_KEY not found in .env")

# -------------------------------
# 3) 요청 함수 (페이지 반복)
# -------------------------------
BASE_URL = "https://opendart.fss.or.kr/api/list.json"

def fetch_page(page_no: int):
    # 개발가이드: crtfc_key, bgn_de, end_de, last_reprt_at, page_no, page_count 등 [1](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
    params = {
        "crtfc_key": API_KEY,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "last_reprt_at": args.last_reprt_at,
        "page_no": page_no,
        "page_count": args.page_count,
        "sort": "date",
        "sort_mth": "desc",
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# -------------------------------
# 4) Raw 저장 경로
# -------------------------------
raw_dir = f"data/raw/filings/{bgn_de}_{end_de}"
os.makedirs(raw_dir, exist_ok=True)

# -------------------------------
# 5) DB 연결
# -------------------------------
db_path = "data/opendart.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# SQLite에서 INSERT OR IGNORE로 멱등 처리
insert_sql = """
INSERT OR IGNORE INTO fact_filing
(rcept_no, corp_code, corp_name, stock_code, corp_cls, report_nm, flr_nm, rcept_dt, rm)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# -------------------------------
# 6) 페이지 반복 수집
# -------------------------------
print(f"🔹 Fetch filings: {bgn_de} ~ {end_de}")

first = fetch_page(1)

# 개발가이드: total_page, list 필드 제공 [1](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
status = first.get("status")
message = first.get("message")
if status != "000":
    raise RuntimeError(f"❌ OpenDART error: status={status}, message={message}")

with open(os.path.join(raw_dir, "page_1.json"), "w", encoding="utf-8") as f:
    json.dump(first, f, ensure_ascii=False, indent=2)

total_page = int(first.get("total_page", 1))
all_rows = []

def extract_rows(payload):
    items = payload.get("list", [])
    rows = []
    for it in items:
        rows.append((
            it.get("rcept_no"),
            it.get("corp_code"),
            it.get("corp_name"),
            it.get("stock_code"),
            it.get("corp_cls"),
            it.get("report_nm"),
            it.get("flr_nm"),
            it.get("rcept_dt"),
            it.get("rm"),
        ))
    return rows

all_rows.extend(extract_rows(first))

for page_no in range(2, total_page + 1):
    payload = fetch_page(page_no)
    if payload.get("status") != "000":
        raise RuntimeError(f"❌ OpenDART error on page {page_no}: {payload.get('status')} {payload.get('message')}")
    with open(os.path.join(raw_dir, f"page_{page_no}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    all_rows.extend(extract_rows(payload))

print(f"✅ Downloaded pages: {total_page}, rows: {len(all_rows):,}")
print("🔹 Inserting into SQLite (idempotent: INSERT OR IGNORE)...")

cur.executemany(insert_sql, all_rows)
conn.commit()

# -------------------------------
# 7) 테스트/검증 출력
# -------------------------------
cur.execute("SELECT COUNT(*) FROM fact_filing;")
total = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM fact_filing WHERE rcept_dt BETWEEN ? AND ?;", (bgn_de, end_de))
in_range = cur.fetchone()[0]

cur.execute("SELECT MAX(rcept_dt) FROM fact_filing;")
max_dt = cur.fetchone()[0]

conn.close()

print("--------------------------------------------------")
print(f"fact_filing 총 건수           : {total:,}")
print(f"이번 범위({bgn_de}~{end_de}) 건수 : {in_range:,}")
print(f"fact_filing 최신 rcept_dt     : {max_dt}")
print("✅ STEP 6 완료")
print("--------------------------------------------------")