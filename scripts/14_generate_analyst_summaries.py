import sqlite3
import json
import duckdb

# --------------------------------------------------
# 설정
# --------------------------------------------------
DB_PATH = "data/opendart.sqlite"
DUCKDB_PATH = "data/analytics.duckdb"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fact_report_analyst_summary (
        rcept_no TEXT PRIMARY KEY,
        summary_json TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_top_reports():
    # DuckDB에서 상위 기업과 매칭되는 rcept_no 가져오기
    con_duck = duckdb.connect(DUCKDB_PATH)
    con_duck.execute("INSTALL sqlite; LOAD sqlite;")
    con_duck.execute(f"ATTACH '{DB_PATH}' AS sdb (TYPE SQLITE);")
    
    df = con_duck.execute("""
        SELECT DISTINCT m.corp_code, m.corp_name, f.rcept_no, b.business_content_txt
        FROM mart_score_combined_annual m
        JOIN sdb.fact_filing f ON m.corp_code = f.corp_code
        JOIN sdb.fact_report_business_content b ON f.rcept_no = b.rcept_no
        WHERE f.report_nm LIKE '%사업보고서%'
          AND f.rcept_no NOT IN (SELECT rcept_no FROM sdb.fact_report_analyst_summary)
        ORDER BY m.combined_score DESC
        LIMIT 20
    """).df()
    con_duck.close()
    return df

def save_summary(rcept_no, summary_dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO fact_report_analyst_summary (rcept_no, summary_json, updated_at)
    VALUES (?, ?, datetime('now'))
    """, (rcept_no, json.dumps(summary_dict, ensure_ascii=False)))
    conn.commit()
    conn.close()

# --------------------------------------------------
# 에이전트에게 요약 요청을 위한 프롬프트 생성 함수
# (이 스크립트는 프롬프트를 출력하고, 사용자가 에이전트를 통해 결과를 채워넣는 방식으로도 활용 가능)
# --------------------------------------------------
def generate_summary_prompt(corp_name, text):
    prompt = f"""
다음은 {corp_name}의 사업보고서 '사업의 내용' 텍스트입니다. 
이를 분석하여 애널리스트 리포트용 요약을 작성해 주세요. 
반드시 다음 JSON 형식을 지켜주세요:
{{
  "business_summary": "3줄 요약",
  "product_mix": [{{ "product": "제품명", "ratio": "비중(%)" }}],
  "investment_point": "투자 포인트 1줄",
  "risk_factor": "리스크 요인 1줄"
}}

텍스트:
{text[:4000]}
"""
    return prompt

if __name__ == "__main__":
    init_db()
    df = get_top_reports()
    if df.empty:
        print("✅ 새로 요약할 보고서가 없습니다.")
    else:
        print(f"🔹 요약 대상 기업: {len(df)}개")
        # 여기서 실제로는 LLM API를 호출하거나, 서브 에이전트에게 위임해야 함
        # 현재 환경에서는 메인 루프에서 순차적으로 프롬프트를 구성하여 서브 에이전트에게 전달
