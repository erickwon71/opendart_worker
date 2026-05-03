import duckdb

# =============================================================================
# 업종(induty_code)별로 "운영 CAPEX"에 포함할 투자 항목을
# 데이터 기반(coverage + intensity)으로 자동 선택하여
# mart_buffett_cash_annual을 재생성하는 스크립트
#
# ✅ 핵심 해결 포인트(이번 이슈):
# - owner_earnings가 전부 NULL이었던 원인: net_income/cfo/revenue 등의 표준계정명이
#   'NET_INCOME'이 아닌 '당기순이익' 등으로 들어가 있었는데, 08_3가 NET_INCOME만 봄
# - 해결: CFO/NET_INCOME/DEPRECIATION/REVENUE는 "동의어(한국어/영문)"를 함께 합산
#
# 입력:
# - DuckDB: mart_financial_base (from 08_2)
# - SQLite: dim_company(induty_code) (from 08_0 backfill)
# - account_std: INV_* / CFO / NET_INCOME / DEPRECIATION / REVENUE 또는 한국어 표준계정
#
# 출력:
# - DuckDB: dim_industry_capex_policy
# - DuckDB: mart_buffett_cash_annual
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

# ---------------- 업종별 자동 선택 기준 ----------------
COVERAGE_TH = 0.20      # 업종 내 20% 이상 기업에서 발생
INTENSITY_TH = 0.005    # 매출 대비 중앙값(|amount|/revenue) ≥ 0.5%

# ---------------- 운영 CAPEX 후보 (Owner Earnings 차감 대상) ----------------
OPERATING_COMPS = [
    "inv_ppe_acq",
    "inv_intang_acq",
    "inv_cip",
    "inv_facility",
    "inv_equipment",
    "inv_software",
    "inv_dev_cost",
]

# ---------------- 확장 투자 후보 (리포트/참고용) ----------------
EXPANDED_COMPS = OPERATING_COMPS + [
    "inv_subsidiary_acq",
    "inv_business_acq",
    "inv_associate",
    "inv_equity_invest",
    "inv_securities",
    "inv_fin_asset",
    "inv_loans",
]

def table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [name]
    ).fetchone()[0] > 0

con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

print("▶ 업종별 CAPEX 자동 선택 cash mart 재생성 시작")

# ---------------- 필수 테이블 확인 ----------------
if not table_exists(con, "mart_financial_base"):
    con.close()
    raise SystemExit("❌ DuckDB에 mart_financial_base가 없습니다. 먼저 08_2_build_duckdb_mart.py 실행하세요.")

try:
    con.execute("SELECT induty_code FROM sdb.dim_company LIMIT 1")
except Exception:
    con.close()
    raise SystemExit("❌ SQLite dim_company.induty_code가 없습니다. 08_0_backfill_induty_code.py 실행하세요.")

# =============================================================================
# 1) tmp_cash_wide 생성 (reprt_code='11011' 사업보고서 기준)
#    - CFO/NET_INCOME/DEPRECIATION/REVENUE는 동의어 포함
# =============================================================================
con.execute("""
CREATE OR REPLACE TABLE tmp_cash_wide AS
WITH base AS (
  SELECT
    f.corp_code,
    f.bsns_year,
    f.fs_div,
    f.account_std,
    f.amount,
    dc.induty_code
  FROM mart_financial_base f
  LEFT JOIN sdb.dim_company dc
    ON f.corp_code = dc.corp_code
  WHERE f.reprt_code = '11011'
),
agg AS (
  SELECT
    corp_code,
    bsns_year,
    fs_div,
    induty_code,

    -- ✅ 동의어 포함: CFO
    SUM(CASE WHEN account_std IN ('CFO','영업활동현금흐름') THEN amount END) AS cfo,

    -- ✅ 동의어 포함: Net Income
    SUM(CASE WHEN account_std IN ('NET_INCOME','당기순이익') THEN amount END) AS net_income,

    -- ✅ 동의어 포함: Depreciation
    SUM(CASE WHEN account_std IN ('DEPRECIATION','감가상각비','감가상각비및무형자산상각비') THEN amount END) AS depreciation,

    -- ✅ 동의어 포함: Revenue
    SUM(CASE WHEN account_std IN ('REVENUE','매출액') THEN amount END) AS revenue,

    -- 운영 CAPEX 후보 (INV_* 표준계정)
    SUM(CASE WHEN account_std='INV_PPE_ACQ'       THEN amount END) AS inv_ppe_acq,
    SUM(CASE WHEN account_std='INV_INTANG_ACQ'    THEN amount END) AS inv_intang_acq,
    SUM(CASE WHEN account_std='INV_CIP'           THEN amount END) AS inv_cip,
    SUM(CASE WHEN account_std='INV_FACILITY'      THEN amount END) AS inv_facility,
    SUM(CASE WHEN account_std='INV_EQUIPMENT'     THEN amount END) AS inv_equipment,
    SUM(CASE WHEN account_std='INV_SOFTWARE'      THEN amount END) AS inv_software,
    SUM(CASE WHEN account_std='INV_DEV_COST'      THEN amount END) AS inv_dev_cost,

    -- 확장 투자 후보 (INV_* 표준계정)
    SUM(CASE WHEN account_std='INV_SUBSIDIARY_ACQ' THEN amount END) AS inv_subsidiary_acq,
    SUM(CASE WHEN account_std='INV_BUSINESS_ACQ'   THEN amount END) AS inv_business_acq,
    SUM(CASE WHEN account_std='INV_ASSOCIATE'      THEN amount END) AS inv_associate,
    SUM(CASE WHEN account_std='INV_EQUITY_INVEST'  THEN amount END) AS inv_equity_invest,
    SUM(CASE WHEN account_std='INV_SECURITIES'     THEN amount END) AS inv_securities,
    SUM(CASE WHEN account_std='INV_FIN_ASSET'      THEN amount END) AS inv_fin_asset,
    SUM(CASE WHEN account_std='INV_LOANS'          THEN amount END) AS inv_loans

  FROM base
  GROUP BY 1,2,3,4
)
SELECT * FROM agg;
""")

# =============================================================================
# 2) 업종별 CAPEX 포함 정책(dim_industry_capex_policy)
#    - 운영 CAPEX 후보(OPERATING_COMPS)만 대상으로 coverage/median intensity 계산
# =============================================================================
con.execute("""
CREATE OR REPLACE TABLE dim_industry_capex_policy AS
WITH long AS (
  SELECT
    induty_code,
    comp_name,
    abs(comp_value) AS abs_value,
    revenue
  FROM (
    SELECT induty_code, revenue, 'inv_ppe_acq'    AS comp_name, inv_ppe_acq    AS comp_value FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_intang_acq', inv_intang_acq FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_cip',        inv_cip        FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_facility',   inv_facility   FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_equipment',  inv_equipment  FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_software',   inv_software   FROM tmp_cash_wide
    UNION ALL
    SELECT induty_code, revenue, 'inv_dev_cost',   inv_dev_cost   FROM tmp_cash_wide
  )
  WHERE induty_code IS NOT NULL AND induty_code != ''
),
stats AS (
  SELECT
    induty_code,
    comp_name,
    AVG(CASE WHEN abs_value IS NOT NULL AND abs_value != 0 THEN 1 ELSE 0 END) AS coverage,
    median(
      CASE WHEN revenue IS NOT NULL AND revenue != 0
           THEN abs_value / revenue
      END
    ) AS med_intensity
  FROM long
  GROUP BY 1,2
)
SELECT
  induty_code,
  comp_name,
  coverage,
  med_intensity,
  CASE
    WHEN coverage >= ? AND med_intensity >= ? THEN 1
    ELSE 0
  END AS use_flag
FROM stats;
""", [COVERAGE_TH, INTENSITY_TH])

# =============================================================================
# 3) mart_buffett_cash_annual 생성
#    - capex_total: 업종별 use_flag로 선택된 운영 CAPEX 합
#    - invest_total: 확장 투자 총액(참고용)
#    - free_cash_flow / owner_earnings: capex_total 기준
# =============================================================================
con.execute("""
CREATE OR REPLACE TABLE mart_buffett_cash_annual AS
WITH w AS (SELECT * FROM tmp_cash_wide),

flags AS (
  SELECT
    induty_code,
    MAX(CASE WHEN comp_name='inv_ppe_acq'    THEN use_flag ELSE 0 END) AS use_inv_ppe_acq,
    MAX(CASE WHEN comp_name='inv_intang_acq' THEN use_flag ELSE 0 END) AS use_inv_intang_acq,
    MAX(CASE WHEN comp_name='inv_cip'        THEN use_flag ELSE 0 END) AS use_inv_cip,
    MAX(CASE WHEN comp_name='inv_facility'   THEN use_flag ELSE 0 END) AS use_inv_facility,
    MAX(CASE WHEN comp_name='inv_equipment'  THEN use_flag ELSE 0 END) AS use_inv_equipment,
    MAX(CASE WHEN comp_name='inv_software'   THEN use_flag ELSE 0 END) AS use_inv_software,
    MAX(CASE WHEN comp_name='inv_dev_cost'   THEN use_flag ELSE 0 END) AS use_inv_dev_cost
  FROM dim_industry_capex_policy
  GROUP BY induty_code
),

calc AS (
  SELECT
    w.corp_code,
    w.bsns_year,
    w.fs_div,
    w.induty_code,

    w.cfo,
    w.net_income,
    w.depreciation,
    w.revenue,

    -- 원 구성요소도 같이 보관(디버깅 용)
    w.inv_ppe_acq,
    w.inv_intang_acq,
    w.inv_cip,
    w.inv_facility,
    w.inv_equipment,
    w.inv_software,
    w.inv_dev_cost,

    w.inv_subsidiary_acq,
    w.inv_business_acq,
    w.inv_associate,
    w.inv_equity_invest,
    w.inv_securities,
    w.inv_fin_asset,
    w.inv_loans,

    -- 운영 CAPEX(업종별 자동 선택)
    (
      (CASE WHEN COALESCE(f.use_inv_ppe_acq,0)=1    THEN COALESCE(w.inv_ppe_acq,0)    ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_intang_acq,0)=1 THEN COALESCE(w.inv_intang_acq,0) ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_cip,0)=1        THEN COALESCE(w.inv_cip,0)        ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_facility,0)=1   THEN COALESCE(w.inv_facility,0)   ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_equipment,0)=1  THEN COALESCE(w.inv_equipment,0)  ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_software,0)=1   THEN COALESCE(w.inv_software,0)   ELSE 0 END) +
      (CASE WHEN COALESCE(f.use_inv_dev_cost,0)=1   THEN COALESCE(w.inv_dev_cost,0)   ELSE 0 END)
    ) AS capex_total,

    -- 확장 투자 총액(참고용)
    (
      COALESCE(w.inv_ppe_acq,0) + COALESCE(w.inv_intang_acq,0) + COALESCE(w.inv_cip,0) +
      COALESCE(w.inv_facility,0) + COALESCE(w.inv_equipment,0) + COALESCE(w.inv_software,0) +
      COALESCE(w.inv_dev_cost,0) +
      COALESCE(w.inv_subsidiary_acq,0) + COALESCE(w.inv_business_acq,0) + COALESCE(w.inv_associate,0) +
      COALESCE(w.inv_equity_invest,0) + COALESCE(w.inv_securities,0) + COALESCE(w.inv_fin_asset,0) +
      COALESCE(w.inv_loans,0)
    ) AS invest_total

  FROM w
  LEFT JOIN flags f
    ON w.induty_code = f.induty_code
)

SELECT
  *,
  -- FCF: CFO - capex_total
  CASE
    WHEN cfo IS NULL THEN NULL
    ELSE cfo - capex_total
  END AS free_cash_flow,

  -- Owner Earnings: Net Income + Depreciation - capex_total
  CASE
    WHEN net_income IS NULL THEN NULL
    ELSE net_income + COALESCE(depreciation,0) - capex_total
  END AS owner_earnings

FROM calc;
""")

# ---------------- 요약 출력 ----------------
rows = con.execute("SELECT COUNT(*) FROM mart_buffett_cash_annual").fetchone()[0]
notnull_oe = con.execute("SELECT COUNT(*) FROM mart_buffett_cash_annual WHERE owner_earnings IS NOT NULL").fetchone()[0]
notnull_ni = con.execute("SELECT COUNT(*) FROM mart_buffett_cash_annual WHERE net_income IS NOT NULL").fetchone()[0]

print(f"✅ mart_buffett_cash_annual 재생성 완료: {rows:,} rows")
print(f"   net_income NOT NULL: {notnull_ni:,}")
print(f"   owner_earnings NOT NULL: {notnull_oe:,}")

con.close()

print("\n👉 다음 단계 실행:")
print("   python scripts/08_4_build_buffett_earning_power_10y.py")
print("   python scripts/09_6_build_yearly_scores.py")
print("   python scripts/10_3_batch_top20_html_reports.py")