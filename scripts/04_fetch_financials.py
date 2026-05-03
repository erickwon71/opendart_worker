"""
04_fetch_financials.py

역할:
- fact_filing 기준으로 재무제표 대상 회사 수집
- OpenDART fnlttSinglAcntAll API 호출
- 재무제표를 정규화하여 SQLite에 저장
- INSERT OR IGNORE → 멱등성 보장

실행:
python scripts/04_fetch_financials.py --year 2024
"""

import os
import requests
import argparse
import sqlite3
from dotenv import load_dotenv

# --------------------------------------------------
# 1. CLI 인자
# --------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, required=True, help="사업연도 (예: 2024)")
args = parser.parse_args()
YEAR = args.year

# --------------------------------------------------
# 2. 환경 변수
# --------------------------------------------------
load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
if not API_KEY:
    raise RuntimeError("❌ DART_API_KEY not found")

BASE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# --------------------------------------------------
# 3. DB 연결
# --------------------------------------------------
conn = sqlite3.connect("data/opendart.sqlite")
cur = conn.cursor()

# --------------------------------------------------
# 4. 재무제표 수집 대상 회사 선정
#    (정기보고서가 있는 회사만)
# --------------------------------------------------
cur.execute("""
SELECT DISTINCT corp_code
FROM fact_filing
WHERE report_nm LIKE '%보고서'
""")
corp_codes = [r[0] for r in cur.fetchall()]
print(f"🔹 재무제표 대상 회사 수: {len(corp_codes)}")

# --------------------------------------------------
# 5. INSERT SQL (멱등)
# --------------------------------------------------
insert_sql = """
INSERT OR IGNORE INTO fact_financial_statement
(corp_code, bsns_year, reprt_code, fs_div, sj_div, account_nm, amount)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# --------------------------------------------------
# 6. API 파라미터
# --------------------------------------------------
REPORT_CODES = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}
FS_DIVS = ["CFS", "OFS"]

inserted = 0

# --------------------------------------------------
# 7. 메인 루프
# --------------------------------------------------
for corp_code in corp_codes:
    for reprt_code in REPORT_CODES.keys():
        for fs_div in FS_DIVS:
            params = {
                "crtfc_key": API_KEY,
                "corp_code": corp_code,
                "bsns_year": YEAR,
                "reprt_code": reprt_code,
                "fs_div": fs_div
            }

            r = requests.get(BASE_URL, params=params, timeout=30)
            data = r.json()

            if data.get("status") != "000":
                continue

            for row in data.get("list", []):
                cur.execute(
                    insert_sql,
                    (
                        corp_code,
                        YEAR,
                        reprt_code,
                        fs_div,
                        row.get("sj_div"),          # BS / IS / CF
                        row.get("account_nm"),
                        float(row.get("thstrm_amount") or 0)
                    )
                )
                inserted += 1

conn.commit()
conn.close()

print("--------------------------------------------------")
print(f"✅ 저장된 재무 레코드 수: {inserted:,}")
print("✅ STEP 7 완료")