import sqlite3
from collections import Counter, defaultdict

DB_PATH = "data/opendart.sqlite"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("▶ CFO / CAPEX / 감가상각 계정 후보 패턴 추출 시작\n")

# --------------------------------------------------
# 1) 현금흐름표(CF) 계정 수집
# --------------------------------------------------
cur.execute("""
SELECT account_nm
FROM fact_financial_statement
WHERE sj_div = 'CF'
  AND account_nm IS NOT NULL
""")

cf_accounts = [row[0].strip() for row in cur.fetchall()]
cf_counter = Counter(cf_accounts)

# --------------------------------------------------
# 2) CAPEX / 감가상각 키워드 정의
# --------------------------------------------------
CFO_KEYWORDS = ["영업활동"]
CAPEX_KEYWORDS = ["유형자산", "무형자산", "투자활동"]
DEPRE_KEYWORDS = ["감가상각", "상각"]

def classify(account):
    if any(k in account for k in CFO_KEYWORDS):
        return "CFO"
    if any(k in account for k in CAPEX_KEYWORDS):
        return "CAPEX"
    if any(k in account for k in DEPRE_KEYWORDS):
        return "DEPRECIATION"
    return None

# --------------------------------------------------
# 3) 분류 & 빈도 집계
# --------------------------------------------------
bucket = defaultdict(Counter)

for acc, cnt in cf_counter.items():
    cls = classify(acc)
    if cls:
        bucket[cls][acc] += cnt

# --------------------------------------------------
# 4) 결과 출력
# --------------------------------------------------
def print_bucket(title, data, top_n=20):
    print(f"\n[{title}] (빈도 상위 {top_n})")
    print("-" * 60)
    for acc, cnt in data.most_common(top_n):
        print(f"{cnt:10,} | {acc}")

print_bucket("CFO 후보 (영업활동 현금흐름)", bucket["CFO"])
print_bucket("CAPEX 후보 (유형/무형자산 취득)", bucket["CAPEX"])
print_bucket("감가상각 후보", bucket["DEPRECIATION"])

conn.close()