"""
ETL 재무제표 수집 진행률 확인 스크립트
- 전체 Job 대비 완료율
- 상태별 Job 개수
- 연도별 커버리지
- 오늘 API 사용량
"""

import sqlite3
from datetime import datetime

conn = sqlite3.connect("data/opendart.sqlite")
cur = conn.cursor()

print("\n================= 재무제표 수집 진행 현황 =================\n")

# ------------------------------------------------------------
# 1. Job 상태별 개수
# ------------------------------------------------------------
cur.execute("""
SELECT status, COUNT(*) 
FROM etl_job_financial
GROUP BY status
""")
rows = cur.fetchall()

status_counts = {status: cnt for status, cnt in rows}
total_jobs = sum(status_counts.values())
done_jobs = status_counts.get("DONE", 0)

print("▶ Job 상태별 현황")
for status, cnt in status_counts.items():
    print(f"  {status:<8}: {cnt:,}")

print(f"\n▶ 전체 Job 수   : {total_jobs:,}")
print(f"▶ 완료 Job 수   : {done_jobs:,}")

if total_jobs > 0:
    progress = done_jobs / total_jobs * 100
    print(f"▶ 진행률        : {progress:.2f}%")

# ------------------------------------------------------------
# 2. 연도별 커버리지 (DONE 기준)
# ------------------------------------------------------------
print("\n▶ 연도별 수집 완료 회사 수 (DONE 기준)")
cur.execute("""
SELECT bsns_year, COUNT(DISTINCT corp_code) AS corp_cnt
FROM etl_job_financial
WHERE status = 'DONE'
GROUP BY bsns_year
ORDER BY bsns_year
""")

for year, cnt in cur.fetchall():
    print(f"  {year}: {cnt:,} 개 기업")

# ------------------------------------------------------------
# 3. 실제 저장된 재무 레코드 수
# ------------------------------------------------------------
cur.execute("""
SELECT COUNT(*) FROM fact_financial_statement
""")
fact_cnt = cur.fetchone()[0]

print(f"\n▶ 저장된 재무 레코드 수: {fact_cnt:,}")

# ------------------------------------------------------------
# 4. 오늘 API 사용량
# ------------------------------------------------------------
today = datetime.now().strftime("%Y%m%d")
cur.execute("""
SELECT used_requests, limit_requests
FROM etl_quota_daily
WHERE run_date = ?
""", (today,))

row = cur.fetchone()
if row:
    used, limit_req = row
    print(f"\n▶ 오늘 API 사용량: {used:,} / {limit_req:,}")
else:
    print("\n▶ 오늘 API 사용 기록 없음")

conn.close()

print("\n===========================================================\n")