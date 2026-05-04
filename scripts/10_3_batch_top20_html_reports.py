import os
import math
import base64
import json
from io import BytesIO

import duckdb
import pandas as pd
import matplotlib.pyplot as plt

# =============================================================================
# 전문가용 Top20 기업 분석 팩트시트 (Analyst Factsheet) 생성
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"
OUT_DIR = "output/company_reports_analyst"
TOPN = 20
YEARS = 10

os.makedirs(OUT_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# 유틸
# -----------------------------------------------------------------------------
def fig_to_base64_png(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def fmt_pct(x, d=1):
    if x is None or (isinstance(x, float) and math.isnan(x)): return "N/A"
    return f"{x*100:.{d}f}%"

def fmt_bn_krw(x):
    if x is None or (isinstance(x, float) and math.isnan(x)): return "0.0"
    return f"{x/1e9:,.1f}"

def safe_name(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum() or ch in (" ","_","-")).strip().replace(" ","_")

# --------------------------------------------------
# DB 연결 및 초기화
# --------------------------------------------------
con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# 최신 연도 확인
latest_year = con.execute("SELECT MAX(year) FROM mart_score_combined_annual").fetchone()[0]

# 상위 기업 리스트 추출 (정성 요약이 있는 경우 우선순위 체감 가능)
top = con.execute("""
SELECT
  a.corp_code, dc.corp_name, a.fs_div, a.combined_score, 
  f.rcept_no, s.summary_json
FROM mart_score_combined_annual a
LEFT JOIN sdb.dim_company dc ON a.corp_code = dc.corp_code
LEFT JOIN sdb.fact_filing f ON a.corp_code = f.corp_code AND f.report_nm LIKE '%사업보고서%'
LEFT JOIN sdb.fact_report_analyst_summary s ON f.rcept_no = s.rcept_no
WHERE a.year = ?
ORDER BY a.combined_score DESC
LIMIT ?
""", [latest_year, TOPN]).df()

print(f"✅ Top {len(top)} 기업 로드 완료 (기준 연도: {latest_year})")

# -----------------------------------------------------------------------------
# 기업별 리포트 생성 루프
# -----------------------------------------------------------------------------
for idx, row in top.iterrows():
    corp_code, corp_name, fs_div = row["corp_code"], row["corp_name"], row["fs_div"]
    rcept_no, summary_json = row["rcept_no"], row["summary_json"]
    rank = idx + 1
    
    # 1) 재무 데이터 로드 (조정 이익 포함)
    df = con.execute("""
    SELECT 
        m.bsns_year, m.total_score, m.buffett_total_score, m.combined_score,
        q.roe, q.opm, 
        b.owner_earnings, b.fcf_margin, c.capex_total, c.revenue,
        adj.adj_net_income, adj.net_income
    FROM mart_score_combined_yearly m
    LEFT JOIN mart_quality_score_yearly q ON m.corp_code=q.corp_code AND m.bsns_year=q.bsns_year AND m.fs_div=q.fs_div
    LEFT JOIN mart_buffett_owner_score_yearly b ON m.corp_code=b.corp_code AND m.bsns_year=b.bsns_year AND m.fs_div=b.fs_div
    LEFT JOIN mart_buffett_cash_annual c ON m.corp_code=c.corp_code AND m.bsns_year=c.bsns_year AND m.fs_div=c.fs_div
    LEFT JOIN mart_adjusted_metrics adj ON m.corp_code=adj.corp_code AND m.bsns_year=adj.bsns_year AND m.fs_div=adj.fs_div
    WHERE m.corp_code=? AND m.fs_div=?
    ORDER BY m.bsns_year ASC
    """, [corp_code, fs_div]).df()

    if df.empty: continue

    # ---------------- 정성 요약 파싱 ----------------
    summary_html = ""
    product_chart_html = ""
    if summary_json:
        s = json.loads(summary_json)
        summary_html = f"""
        <div class="analyst-note">
            <h3>📝 Analyst's View</h3>
            <p><b>Business:</b> {s.get('business_summary')}</p>
            <p><span class="tag tag-pos">Investment Point</span> {s.get('investment_point')}</p>
            <p><span class="tag tag-neg">Risk Factor</span> {s.get('risk_factor')}</p>
        </div>
        """
        # Product Mix 차트 (있을 경우)
        pmix = s.get('product_mix', [])
        if pmix:
            try:
                labels = []
                sizes = []
                for p in pmix:
                    ratio_str = p.get('ratio', '0').replace('%', '').strip()
                    try:
                        val = float(ratio_str)
                        labels.append(p['product'])
                        sizes.append(val)
                    except ValueError:
                        continue
                
                if sizes:
                    fig_p, ax_p = plt.subplots(figsize=(6, 4))
                    ax_p.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, colors=plt.cm.Paired.colors)
                    ax_p.set_title("Product Mix")
                    img_pmix = fig_to_base64_png(fig_p)
                    product_chart_html = f'<div class="card"><b>매출 구성 (Product Mix)</b><br/><img src="data:image/png;base64,{img_pmix}"/></div>'
            except Exception as e:
                print(f"⚠️ Product Mix 차트 생성 실패 ({corp_name}): {e}")
                product_chart_html = ""

    # ---------------- 그래프 생성 ----------------
    # Chart 1: Quality vs Buffett Score
    fig1, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(df["bsns_year"], df["total_score"], 'o-', label="Quality Score")
    ax1.plot(df["bsns_year"], df["buffett_total_score"], 's-', label="Buffett Score")
    ax1.set_title("Fundamental Score Trend")
    ax1.legend(); ax1.grid(alpha=0.3)
    img_scores = fig_to_base64_png(fig1)

    # Chart 2: Profitability (ROE, OPM, FCF)
    fig2, ax2 = plt.subplots(figsize=(10, 4))
    ax2.plot(df["bsns_year"], df["roe"], 'o-', label="ROE")
    ax2.plot(df["bsns_year"], df["opm"], 'x-', label="OPM")
    ax2.plot(df["bsns_year"], df["fcf_margin"], 'd-', label="FCF Margin")
    ax2.set_title("Key Profitability Ratios")
    ax2.legend(); ax2.grid(alpha=0.3)
    img_ratios = fig_to_base64_png(fig2)

    # Chart 3: Quality of Earnings (NI vs Adj NI vs OE)
    fig3, ax3 = plt.subplots(figsize=(10, 4))
    x = range(len(df))
    ax3.bar([i-0.2 for i in x], df["net_income"]/1e9, width=0.2, label="Net Income")
    ax3.bar([i for i in x], df["adj_net_income"]/1e9, width=0.2, label="Adj Net Income")
    ax3.bar([i+0.2 for i in x], df["owner_earnings"]/1e9, width=0.2, label="Owner Earnings")
    ax3.set_xticks(x); ax3.set_xticklabels(df["bsns_year"])
    ax3.set_title("Quality of Earnings (₩ bn)")
    ax3.legend(); ax3.grid(axis='y', alpha=0.3)
    img_earnings = fig_to_base64_png(fig3)

    # ---------------- HTML 템플릿 ----------------
    dart_link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "#"
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>#{rank} {corp_name} Analyst Factsheet</title>
        <style>
            body {{ font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #333; max-width: 1000px; margin: 40px auto; padding: 20px; background: #f9f9f9; }}
            h1 {{ color: #1a202c; border-bottom: 3px solid #3182ce; padding-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }}
            .rank {{ background: #3182ce; color: white; padding: 4px 12px; border-radius: 8px; font-size: 0.6em; }}
            .analyst-note {{ background: #ebf8ff; border-left: 5px solid #3182ce; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .tag {{ padding: 2px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; margin-right: 5px; }}
            .tag-pos {{ background: #c6f6d5; color: #22543d; }}
            .tag-neg {{ background: #fed7d7; color: #822727; }}
            .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            img {{ width: 100%; height: auto; border-radius: 8px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9em; }}
            th, td {{ padding: 12px; text-align: right; border-bottom: 1px solid #edf2f7; }}
            th {{ background: #f7fafc; color: #4a5568; }}
            .trace-link {{ font-size: 0.8em; color: #3182ce; text-decoration: none; }}
        </style>
    </head>
    <body>
        <h1>
            <div><span class="rank">Rank #{rank}</span> {corp_name} ({corp_code})</div>
            <a href="{dart_link}" target="_blank" class="trace-link">🔗 원문 공시 보기 (DART)</a>
        </h1>
        
        {summary_html}
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            {product_chart_html}
            <div class="card">
                <b>핵심 지표 요약</b>
                <table>
                    <tr><th>ROE</th><td>{fmt_pct(df.iloc[-1]['roe'])}</td></tr>
                    <tr><th>OPM</th><td>{fmt_pct(df.iloc[-1]['opm'])}</td></tr>
                    <tr><th>FCF Margin</th><td>{fmt_pct(df.iloc[-1]['fcf_margin'])}</td></tr>
                    <tr><th>Adj NI (bn)</th><td>{fmt_bn_krw(df.iloc[-1]['adj_net_income'])}</td></tr>
                </table>
            </div>
        </div>

        <div class="card"><b>① 펀더멘털 스코어 추이</b><br/><img src="data:image/png;base64,{img_scores}"/></div>
        <div class="card"><b>② 수익성 지표 (ROE/OPM/FCF)</b><br/><img src="data:image/png;base64,{img_ratios}"/></div>
        <div class="card"><b>③ 이익의 질 (NI vs Adj NI vs Owner Earnings)</b><br/><img src="data:image/png;base64,{img_earnings}"/></div>
        
    </body>
    </html>
    """
    
    file_name = f"rank{rank:02d}_{corp_code}_{safe_name(corp_name)}.html"
    with open(os.path.join(OUT_DIR, file_name), "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ 리포트 생성 완료: {file_name}")

con.close()
