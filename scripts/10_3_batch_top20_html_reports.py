import os
import math
import base64
from io import BytesIO

import duckdb
import pandas as pd
import matplotlib.pyplot as plt

# =============================================================================
# Top20 기업 HTML 리포트 배치 생성
#
# 입력(DuckDB):
# - mart_score_combined_annual         (Top 기준 연도/점수)
# - mart_score_combined_yearly         (연도별 점수)
# - mart_quality_score_yearly          (roe, opm)
# - mart_buffett_owner_score_yearly    (owner_earnings, fcf_margin)
# - mart_buffett_cash_annual           (capex_total, revenue, free_cash_flow)
# - mart_buffett_earning_power_10y     (요약 문구)
#
# 입력(SQLite):
# - dim_company (corp_name)
#
# 출력:
# - output/company_reports_top20/*.html
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

OUT_DIR = "output/company_reports_top20"
TOPN = 20
YEARS = 10
MIN_YEARS = 5

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
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "N/A"
    return f"{x*100:.{d}f}%"

def fmt_bn_krw(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "0.0"
    return f"{x/1e9:,.1f}"

def safe_name(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum() or ch in (" ","_","-")).strip().replace(" ","_")

def table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?",
        [name]
    ).fetchone()[0] > 0

# -----------------------------------------------------------------------------
# DB 연결
# -----------------------------------------------------------------------------
con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# -----------------------------------------------------------------------------
# 필수 테이블 체크
# -----------------------------------------------------------------------------
required = [
    "mart_score_combined_annual",
    "mart_score_combined_yearly",
    "mart_quality_score_yearly",
    "mart_buffett_owner_score_yearly",
    "mart_buffett_cash_annual",
    "mart_buffett_earning_power_10y",
]
for t in required:
    if not table_exists(con, t):
        con.close()
        raise SystemExit(f"❌ 필수 테이블 없음: {t}")

# -----------------------------------------------------------------------------
# Top 기준 연도
# -----------------------------------------------------------------------------
latest_year = con.execute(
    "SELECT MAX(year) FROM mart_score_combined_annual"
).fetchone()[0]
print(f"▶ Top{TOPN} 기준 연도: {latest_year}")

# -----------------------------------------------------------------------------
# TopN 리스트
# -----------------------------------------------------------------------------
top = con.execute("""
SELECT
  a.corp_code,
  dc.corp_name,
  a.fs_div,
  a.combined_score,
  a.total_score,
  a.buffett_total_score
FROM mart_score_combined_annual a
LEFT JOIN sdb.dim_company dc
  ON a.corp_code = dc.corp_code
WHERE a.year = ?
ORDER BY a.combined_score DESC
LIMIT ?
""", [latest_year, TOPN]).df()

print(f"✅ Top {len(top)}개 기업 로드 완료")

generated, skipped = 0, 0

# -----------------------------------------------------------------------------
# 기업별 리포트
# -----------------------------------------------------------------------------
for idx, row in top.iterrows():
    corp_code = row["corp_code"]
    corp_name = row["corp_name"] if row["corp_name"] else corp_code
    fs_div = row["fs_div"]

    # 1) 연도별 점수
    df_s = con.execute("""
    SELECT
      bsns_year,
      total_score,
      buffett_total_score,
      combined_score
    FROM mart_score_combined_yearly
    WHERE corp_code=? AND fs_div=?
    ORDER BY bsns_year DESC
    LIMIT ?
    """, [corp_code, fs_div, YEARS]).df()

    if df_s.empty or len(df_s) < MIN_YEARS:
        print(f" - SKIP (5년 미만): {corp_name} {corp_code} {fs_div}")
        skipped += 1
        continue

    df_s = df_s.sort_values("bsns_year")

    # 2) Quality
    df_q = con.execute("""
    SELECT bsns_year, roe, opm
    FROM mart_quality_score_yearly
    WHERE corp_code=? AND fs_div=?
    """, [corp_code, fs_div]).df()

    # 3) Owner/FCF
    df_b = con.execute("""
    SELECT bsns_year, owner_earnings, fcf_margin
    FROM mart_buffett_owner_score_yearly
    WHERE corp_code=? AND fs_div=?
    """, [corp_code, fs_div]).df()

    # 4) Cash (CAPEX는 capex_total 사용)
    df_c = con.execute("""
    SELECT bsns_year, capex_total, revenue, free_cash_flow
    FROM mart_buffett_cash_annual
    WHERE corp_code=? AND fs_div=?
    """, [corp_code, fs_div]).df()

    df = (
        df_s.merge(df_q, on="bsns_year", how="left")
            .merge(df_b, on="bsns_year", how="left")
            .merge(df_c, on="bsns_year", how="left")
    )

    # CAPEX outflow로 표시(현금 유출을 양수)
    def to_outflow(x):
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return abs(x)
    df["capex_outflow"] = df["capex_total"].apply(to_outflow)

    # 5) 10y 요약
    summ = con.execute("""
    SELECT start_year, end_year, years_used,
           avg_owner_earnings, avg_fcf_margin, positive_owner_ratio,
           avg_capex_intensity, avg_roe, std_roe,
           earning_power_score
    FROM mart_buffett_earning_power_10y
    WHERE corp_code=? AND fs_div=?
    """, [corp_code, fs_div]).fetchone()

    if summ:
        (sy, ey, years_used, avg_oe, avg_fcfm, pos_ratio,
         avg_capint, avg_roe, std_roe, epscore) = summ
        summary = (
            f"{sy}~{ey} ({years_used}년) 평균 Owner Earnings {avg_oe:,.0f}원, "
            f"양(+) 유지 {fmt_pct(pos_ratio)}, "
            f"평균 FCF 마진 {fmt_pct(avg_fcfm)}, "
            f"CAPEX/매출 {fmt_pct(avg_capint)}, "
            f"ROE 평균 {fmt_pct(avg_roe)} (변동성 {fmt_pct(std_roe,1).replace('%','%p')}). "
            f"Earning Power Score={epscore}"
        )
    else:
        summary = "5~10년 Earning Power 요약 데이터 없음"

    # ---------------- 그래프 ① 점수 ----------------
    fig1 = plt.figure(figsize=(12,4))
    ax1 = fig1.add_subplot(1,1,1)
    ax1.plot(df["bsns_year"], df["total_score"], marker="o", label="Quality")
    ax1.plot(df["bsns_year"], df["buffett_total_score"], marker="o", label="Buffett")
    ax1.plot(df["bsns_year"], df["combined_score"], marker="o", label="Combined")
    ax1.set_title("Score Trend")
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    img_scores = fig_to_base64_png(fig1)

    # ---------------- 그래프 ② 비율 ----------------
    fig2 = plt.figure(figsize=(12,4))
    ax2 = fig2.add_subplot(1,1,1)
    ax2.plot(df["bsns_year"], df["roe"], marker="o", label="ROE")
    ax2.plot(df["bsns_year"], df["opm"], marker="o", label="OPM")
    ax2.plot(df["bsns_year"], df["fcf_margin"], marker="o", label="FCF Margin")
    ax2.set_title("Key Ratios")
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    img_ratios = fig_to_base64_png(fig2)

    # ---------------- 그래프 ③ OE vs CAPEX ----------------
    fig3 = plt.figure(figsize=(12,4))
    ax3 = fig3.add_subplot(1,1,1)
    x = range(len(df))
    oe = [(0 if pd.isna(v) else v/1e9) for v in df["owner_earnings"]]
    cap = [(0 if pd.isna(v) else v/1e9) for v in df["capex_outflow"]]
    ax3.bar([i-0.2 for i in x], oe, width=0.4, label="Owner Earnings (₩ bn)")
    ax3.bar([i+0.2 for i in x], cap, width=0.4, label="CAPEX Outflow (₩ bn)")
    ax3.axhline(0, color="black", lw=0.8)
    ax3.set_xticks(list(x))
    ax3.set_xticklabels(df["bsns_year"])
    ax3.set_title("Owner Earnings vs CAPEX")
    ax3.grid(True, axis="y", alpha=0.3)
    ax3.legend()
    img_cash = fig_to_base64_png(fig3)

    # ---------------- 표 ----------------
    dv = df.copy()
    dv["roe"] = dv["roe"].apply(fmt_pct)
    dv["opm"] = dv["opm"].apply(fmt_pct)
    dv["fcf_margin"] = dv["fcf_margin"].apply(fmt_pct)
    dv["owner_earnings"] = dv["owner_earnings"].apply(fmt_bn_krw)
    dv["capex_outflow"] = dv["capex_outflow"].apply(fmt_bn_krw)
    dv["combined_score"] = dv["combined_score"].apply(lambda v: f"{v:.4f}" if pd.notna(v) else "")
    dv["total_score"] = dv["total_score"].apply(lambda v: f"{int(v)}" if pd.notna(v) else "")
    dv["buffett_total_score"] = dv["buffett_total_score"].apply(lambda v: f"{int(v)}" if pd.notna(v) else "")
    dv = dv[["bsns_year","total_score","buffett_total_score","combined_score",
             "roe","opm","fcf_margin","owner_earnings","capex_outflow"]]
    table_html = dv.to_html(index=False, escape=False)

    # ---------------- HTML ----------------
    rank = idx + 1
    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>#{rank} {corp_name} ({corp_code}) [{fs_div}]</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',Arial;margin:32px}}
 .card{{border:1px solid #eee;border-radius:12px;padding:16px;margin:14px 0}}
 img{{max-width:100%;border:1px solid #eee;border-radius:12px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #ddd;padding:6px 10px;text-align:right}}
 th{{background:#f7f7f7}}
 td:first-child,th:first-child{{text-align:center}}
</style>
</head>
<body>
<h1>#{rank} {corp_name} <span>({corp_code})</span></h1>
<div class="card">{summary}</div>
<div class="card"><b>① 점수 추이</b><br/>data:image/png;base64,{img_scores}</div>
<div class="card"><b>② 핵심 비율</b><br/>data:image/png;base64,{img_ratios}</div>
<div class="card"><b>③ OE vs CAPEX</b><br/>data:image/png;base64,{img_cash}</div>
<div class="card"><b>④ 연도별 표</b>{table_html}</div>
</body>
</html>"""

    fname = f"rank{rank:02d}_{corp_code}_{fs_div}_{safe_name(corp_name)}.html"
    with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 생성: {fname}")
    generated += 1

con.close()
print(f"\n🎉 완료: 생성 {generated}, 스킵 {skipped}")