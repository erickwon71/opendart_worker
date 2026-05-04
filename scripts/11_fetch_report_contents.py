import os
import sqlite3
import requests
import zipfile
import io
import time
from dotenv import load_dotenv

# --------------------------------------------------
# 설정
# --------------------------------------------------
load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
DB_PATH = "data/opendart.sqlite"
REPORT_DIR = "data/raw/reports"

if not API_KEY:
    raise RuntimeError("❌ DART_API_KEY not found in .env")

os.makedirs(REPORT_DIR, exist_ok=True)

# --------------------------------------------------
# DB 초기화 (다운로드 상태 추적용)
# --------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_report_download (
        rcept_no TEXT PRIMARY KEY,
        status TEXT, -- PENDING, DONE, FAILED
        last_error TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_pending_reports():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 사업보고서 위주로 먼저 수집
    cur.execute("""
    SELECT rcept_no 
    FROM fact_filing 
    WHERE (report_nm LIKE '%사업보고서 (2023.12)%' OR report_nm LIKE '%사업보고서 (2024.12)%')
      AND rcept_no NOT IN (SELECT rcept_no FROM fact_report_download WHERE status='DONE')
    LIMIT 100 -- 테스트를 위해 100개씩 진행
    """)
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def update_status(rcept_no, status, error=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO fact_report_download (rcept_no, status, last_error, updated_at)
    VALUES (?, ?, ?, datetime('now'))
    """, (rcept_no, status, error))
    conn.commit()
    conn.close()

# --------------------------------------------------
# 다운로드 및 압축 해제
# --------------------------------------------------
def download_report(rcept_no):
    url = "https://opendart.fss.or.kr/api/document.xml"
    params = {
        "crtfc_key": API_KEY,
        "rcept_no": rcept_no
    }
    
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        
        # 응답이 XML(에러)인지 ZIP인지 확인
        if r.headers.get('Content-Type') == 'application/x-zip-alpha' or r.content[:2] == b'PK':
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                extract_path = os.path.join(REPORT_DIR, rcept_no)
                os.makedirs(extract_path, exist_ok=True)
                z.extractall(extract_path)
            return True, None
        else:
            # 에러 메시지(XML) 파싱 시도
            return False, f"Not a ZIP file: {r.text[:100]}"
            
    except Exception as e:
        return False, str(e)

# --------------------------------------------------
# 메인
# --------------------------------------------------
def main():
    init_db()
    targets = get_pending_reports()
    print(f"🔹 대상 보고서 수: {len(targets)}")

    for i, rcept_no in enumerate(targets):
        print(f"[{i+1}/{len(targets)}] {rcept_no} 다운로드 중...", end="\r")
        success, error = download_report(rcept_no)
        
        if success:
            update_status(rcept_no, "DONE")
        else:
            update_status(rcept_no, "FAILED", error)
            print(f"\n❌ {rcept_no} 실패: {error}")
        
        # API 부하 방지
        time.sleep(0.1)

    print("\n✅ 보고서 수집 완료")

if __name__ == "__main__":
    main()
