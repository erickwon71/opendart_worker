"""
상장사 × (2015~현재) × (사업/반기/1Q/3Q) × (CFS/OFS)
재무제표 수집 Job을 생성한다.
"""

import sqlite3
from datetime import datetime

START_YEAR = 2015
CURRENT_YEAR = datetime.now().year

REPORT_CODES = ["11011", "11012", "11013", "11014"]
FS_DIVS = ["CFS", "OFS"]

conn = sqlite3.connect("data/opendart.sqlite")
cur = conn.cursor()

# 상장사만 추출 (stock_code 존재)
cur.execute("""
SELECT corp_code
FROM dim_company
WHERE
    stock_code IS NOT NULL
    AND LENGTH(stock_code)=6
    AND corp_name NOT LIKE '%스팩%'
    AND corp_name NOT LIKE '%SPAC%'
    AND corp_name NOT LIKE '%펀드%'
    AND corp_name NOT LIKE '%FUND%'
    AND corp_name NOT LIKE '%투자신탁%'
    AND corp_name NOT LIKE '%투자회사%'
    AND corp_name NOT LIKE '%리츠%'
    AND corp_name NOT LIKE '%REIT%'
    AND corp_name NOT LIKE '%특수목적%'
    AND corp_name NOT LIKE '%유동화%'
""")
corp_codes = [r[0] for r in cur.fetchall()]

jobs = []
for corp_code in corp_codes:
    for year in range(START_YEAR, CURRENT_YEAR + 1):
        for reprt in REPORT_CODES:
            for fs in FS_DIVS:
                jobs.append((corp_code, year, reprt, fs))

cur.executemany("""
INSERT OR IGNORE INTO etl_job_financial
(corp_code, bsns_year, reprt_code, fs_div)
VALUES (?, ?, ?, ?)
""", jobs)

conn.commit()
conn.close()

print(f"✅ Job 생성 완료: {len(jobs):,} 개 시도")