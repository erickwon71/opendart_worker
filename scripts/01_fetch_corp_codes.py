"""
01_fetch_corp_codes.py

역할:
- OpenDART corpCode.xml 다운로드
- ZIP 압축 해제
- XML 파싱
- dim_company 테이블에 회사 마스터 적재

실행:
python scripts/01_fetch_corp_codes.py
"""

import os
import io
import zipfile
import requests
import pandas as pd
from lxml import etree
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# --------------------------------------------------
# 1. 환경 변수 로드 (macOS + python-dotenv)
# --------------------------------------------------
load_dotenv()
API_KEY = os.getenv("DART_API_KEY")

if not API_KEY:
    raise RuntimeError("❌ DART_API_KEY not found in .env")

# --------------------------------------------------
# 2. 경로 설정
# --------------------------------------------------
RAW_DIR = "data/raw"
ZIP_PATH = os.path.join(RAW_DIR, "corpCode.zip")
XML_PATH = os.path.join(RAW_DIR, "CORPCODE.xml")
DB_PATH = "sqlite:///data/opendart.sqlite"

os.makedirs(RAW_DIR, exist_ok=True)

# --------------------------------------------------
# 3. corpCode.zip 다운로드
# --------------------------------------------------
print("🔹 Downloading corpCode.xml from OpenDART...")

url = "https://opendart.fss.or.kr/api/corpCode.xml"
params = {"crtfc_key": API_KEY}

res = requests.get(url, params=params)
res.raise_for_status()

with open(ZIP_PATH, "wb") as f:
    f.write(res.content)

print("✅ corpCode.zip downloaded")

# --------------------------------------------------
# 4. ZIP 압축 해제 → CORPCODE.xml
# --------------------------------------------------
with zipfile.ZipFile(io.BytesIO(res.content)) as z:
    z.extractall(RAW_DIR)

if not os.path.exists(XML_PATH):
    raise RuntimeError("❌ CORPCODE.xml not found after extraction")

print("✅ CORPCODE.xml extracted")

# --------------------------------------------------
# 5. XML 파싱
# --------------------------------------------------
print("🔹 Parsing CORPCODE.xml...")

tree = etree.parse(XML_PATH)
rows = []

for el in tree.xpath("//list"):
    corp_code = el.findtext("corp_code")
    corp_name = el.findtext("corp_name")
    stock_code = el.findtext("stock_code")
    modify_date = el.findtext("modify_date")

    rows.append({
        "corp_code": corp_code,
        "corp_name": corp_name,
        "stock_code": stock_code,
        "modify_date": modify_date
    })

df = pd.DataFrame(rows)

print(f"✅ Parsed {len(df):,} companies")

# --------------------------------------------------
# 6. SQLite(dim_company) 적재
# --------------------------------------------------
engine = create_engine(DB_PATH)

with engine.begin() as conn:
    # 테이블이 없으면 생성 (안전장치)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dim_company (
            corp_code TEXT PRIMARY KEY,
            stock_code TEXT,
            corp_name TEXT NOT NULL,
            market TEXT,
            modify_date TEXT
        );
    """))

# replace 전략:
# - 회사 마스터는 "전체 스냅샷"이므로 통째로 갱신
df.to_sql(
    "dim_company",
    engine,
    if_exists="replace",
    index=False
)

print("✅ dim_company table updated")

# --------------------------------------------------
# 7. 간단 무결성 체크
# --------------------------------------------------
with engine.connect() as conn:
    total = conn.execute(
        text("SELECT COUNT(*) FROM dim_company")
    ).scalar()

    invalid_corp_code = conn.execute(
        text("SELECT COUNT(*) FROM dim_company WHERE LENGTH(corp_code) != 8")
    ).scalar()

print("--------------------------------------------------")
print(f"총 회사 수       : {total:,}")
print(f"corp_code 오류수 : {invalid_corp_code}")
print("✅ Step 5 완료")