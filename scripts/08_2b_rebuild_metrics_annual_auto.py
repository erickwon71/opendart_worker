import duckdb
import re

DUCKDB_PATH = "data/analytics.duckdb"

# account_std 후보를 자동 탐색할 키워드(한국어+영문)
CANDIDATE_RULES = {
    "revenue": [
        r"매출", r"수익", r"영업수익", r"Revenue", r"revenue", r"Sales", r"sales"
    ],
    "op_income": [
        r"영업이익", r"영업이익\(손실\)", r"Operating", r"op income", r"OP_INCOME"
    ],
    "net_income": [
        r"당기순이익", r"순이익", r"Net Income", r"NET_INCOME"
    ],
    "assets": [
        r"자산총계", r"총자산", r"Assets", r"ASSETS"
    ],
    "liabilities": [
        r"부채총계", r"총부채", r"Liabilities", r"LIABILITIES"
    ],
    "equity": [
        r"자본총계", r"총자본", r"Equity", r"EQUITY"
    ]
}

def pick_candidates(rows, patterns):
    # rows: list of (account_std, cnt)
    out = []
    for acc, cnt in rows:
        for p in patterns:
            if re.search(p, acc, re.IGNORECASE):
                out.append(acc)
                break
    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq

con = duckdb.connect(DUCKDB_PATH)

# account_std 분포에서 후보 찾기 (사업보고서, 손익+재무상태 둘 다 보려면 sj_div 필터 제거)
rows = con.execute("""
SELECT account_std, COUNT(*) cnt
FROM mart_financial_base
WHERE reprt_code='11011'
  AND account_std IS NOT NULL
GROUP BY 1
ORDER BY cnt DESC
""").fetchall()

# 각 지표별 후보 리스트
cands = {k: pick_candidates(rows, pats) for k, pats in CANDIDATE_RULES.items()}

print("▶ 자동 탐색된 account_std 후보")
for k, v in cands.items():
    print(f" - {k}: {v[:8]}{' ...' if len(v) > 8 else ''}")

# 필수 후보(매출/영업이익/순이익/자본)가 하나도 없으면 중단
must = ["revenue", "op_income", "net_income", "equity"]
for k in must:
    if len(cands[k]) == 0:
        con.close()
        raise SystemExit(f"❌ '{k}' 후보 account_std를 찾지 못했습니다. 위 분포 출력에서 실제 계정명을 확인 후 rules를 보강하세요.")

def in_list_sql(values):
    return "(" + ",".join([f"'{v}'" for v in values]) + ")"

REV = in_list_sql(cands["revenue"])
OPI = in_list_sql(cands["op_income"])
NI  = in_list_sql(cands["net_income"])
AS  = in_list_sql(cands["assets"]) if cands["assets"] else "('___NO_MATCH___')"
LB  = in_list_sql(cands["liabilities"]) if cands["liabilities"] else "('___NO_MATCH___')"
EQ  = in_list_sql(cands["equity"])

print("\n▶ mart_metrics_annual 재생성 시작 (자동 후보 기반)")

con.execute(f"""
CREATE OR REPLACE TABLE mart_metrics_annual AS
WITH base AS (
  SELECT *
  FROM mart_financial_base
  WHERE reprt_code='11011'
),
wide AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,

    MAX(CASE WHEN account_std IN {REV} THEN amount END) AS revenue,
    MAX(CASE WHEN account_std IN {OPI} THEN amount END) AS op_income,
    MAX(CASE WHEN account_std IN {NI}  THEN amount END) AS net_income,

    MAX(CASE WHEN account_std IN {AS}  THEN amount END) AS assets,
    MAX(CASE WHEN account_std IN {LB}  THEN amount END) AS liabilities,
    MAX(CASE WHEN account_std IN {EQ}  THEN amount END) AS equity

  FROM base
  GROUP BY corp_code, bsns_year, fs_div
)
SELECT
  corp_code,
  bsns_year,
  fs_div,
  revenue,
  op_income,
  net_income,
  assets,
  liabilities,
  equity,
  CASE WHEN equity IS NOT NULL AND equity != 0 THEN net_income / equity END AS roe,
  CASE WHEN revenue IS NOT NULL AND revenue != 0 THEN op_income / revenue END AS opm,
  CASE WHEN assets IS NOT NULL AND assets != 0 THEN liabilities / assets END AS debt_ratio
FROM wide;
""")

con.execute("""
CREATE OR REPLACE TABLE mart_growth_annual AS
WITH m AS (
  SELECT corp_code, fs_div, bsns_year, revenue, op_income, net_income
  FROM mart_metrics_annual
),
lagged AS (
  SELECT
    corp_code,
    fs_div,
    bsns_year,
    revenue,
    op_income,
    net_income,
    LAG(revenue) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_revenue,
    LAG(op_income) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_op_income,
    LAG(net_income) OVER (PARTITION BY corp_code, fs_div ORDER BY bsns_year) AS prev_net_income
  FROM m
)
SELECT
  corp_code,
  fs_div,
  bsns_year,
  revenue,
  op_income,
  net_income,
  CASE WHEN prev_revenue IS NOT NULL AND prev_revenue != 0
       THEN (revenue - prev_revenue) / prev_revenue END AS yoy_revenue,
  CASE WHEN prev_op_income IS NOT NULL AND prev_op_income != 0
       THEN (op_income - prev_op_income) / prev_op_income END AS yoy_op_income,
  CASE WHEN prev_net_income IS NOT NULL AND prev_net_income != 0
       THEN (net_income - prev_net_income) / prev_net_income END AS yoy_net_income
FROM lagged;
""")

# 검증 출력
total = con.execute("SELECT COUNT(*) FROM mart_metrics_annual").fetchone()[0]
nonnull = con.execute("SELECT COUNT(*) FROM mart_metrics_annual WHERE revenue IS NOT NULL AND roe IS NOT NULL AND opm IS NOT NULL").fetchone()[0]
print("✅ mart_metrics_annual 재생성 완료")
print(f"   total rows: {total:,}")
print(f"   revenue&roe&opm not null rows: {nonnull:,}")

con.close()

print("\n👉 다음 실행:")
print("   python scripts/09_6_build_yearly_scores.py")
print("   python scripts/10_3_batch_top20_html_reports.py")