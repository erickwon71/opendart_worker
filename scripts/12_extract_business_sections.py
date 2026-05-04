import os
import sqlite3
import re
from bs4 import BeautifulSoup

# --------------------------------------------------
# 설정
# --------------------------------------------------
DB_PATH = "data/opendart.sqlite"
REPORT_DIR = "data/raw/reports"

# --------------------------------------------------
# DB 초기화
# --------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_report_business_content (
        rcept_no TEXT PRIMARY KEY,
        business_content_txt TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_downloaded_reports():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT rcept_no FROM fact_report_download 
    WHERE status='DONE'
      AND rcept_no NOT IN (SELECT rcept_no FROM fact_report_business_content)
    """)
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def save_content(rcept_no, text):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO fact_report_business_content (rcept_no, business_content_txt, updated_at)
    VALUES (?, ?, datetime('now'))
    """, (rcept_no, text))
    conn.commit()
    conn.close()

# --------------------------------------------------
# 추출 로직
# --------------------------------------------------
def extract_business_section(xml_path):
    if not os.path.exists(xml_path):
        return None
    
    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # "II. 사업의 내용" 과 "III. 재무에 관한 사항" 사이를 찾음
    # TITLE 태그 내의 텍스트를 기준으로 범위를 정함
    # DART XML 특성상 TITLE 태그에 섹션 번호가 포함됨
    
    soup = BeautifulSoup(content, "xml")
    titles = soup.find_all("TITLE")
    
    start_node = None
    end_node = None
    
    for t in titles:
        txt = t.get_text().strip()
        if "II. 사업의 내용" in txt or "Ⅱ. 사업의 내용" in txt:
            start_node = t
        elif "III. 재무에 관한 사항" in txt or "Ⅲ. 재무에 관한 사항" in txt:
            end_node = t
            if start_node: break
            
    if not start_node:
        return None
    
    # 섹션 사이의 모든 텍스트 수집
    parts = []
    curr = start_node.next_sibling
    while curr and curr != end_node:
        if hasattr(curr, "get_text"):
            parts.append(curr.get_text(separator="\n", strip=True))
        curr = curr.next_sibling
        
    return "\n".join(parts)

# --------------------------------------------------
# 메인
# --------------------------------------------------
def main():
    init_db()
    rcept_nos = get_downloaded_reports()
    print(f"🔹 처리 대상 보고서: {len(rcept_nos)}")
    
    for i, rcept_no in enumerate(rcept_nos):
        xml_path = os.path.join(REPORT_DIR, rcept_no, f"{rcept_no}.xml")
        print(f"[{i+1}/{len(rcept_nos)}] {rcept_no} 파싱 중...", end="\r")
        
        text = extract_business_section(xml_path)
        if text:
            # 너무 길면 LLM 처리에 부담이 되므로 적당히 자르거나 핵심만 보관할 수도 있으나
            # 일단 전체 저장 (나중에 요약)
            save_content(rcept_no, text)
        else:
            print(f"\n⚠️ {rcept_no}: '사업의 내용' 섹션을 찾지 못함")

    print("\n✅ 텍스트 추출 완료")

if __name__ == "__main__":
    main()
