import duckdb

# =============================================================================
# 업종(induty_code)별로 "운영 CAPEX"에 포함할 투자 항목을
# 데이터 기반(coverage + intensity)으로 자동 선택하여
# mart_buffett_cash_annual을 재생성하는 스크립트
#
# 전제:
# - induty_code는 SQLite(dim_company)에 존재
# - INV_* 표준계정은 이미 account_standardize 단계에서 생성됨
# - 이 스크립트는 DuckDB만 사용 (SQLite는 ATTACH로 참조만)
#
# 결과:
# - mart_buffett_cash_annual
#   * capex_total    : 업종별 자동 선택된 "운영 투자"
#   * invest_total   : 확장 투자 총액(참고용)
#   * free_cash_flow / owner_earnings : capex_total 기준
#
# 주의:
# - 금융자산/지분투자 등은 invest_total에는 포함
# - Owner Earnings 차감에는 사용하지 않음 (왜곡 방지)
# =============================================================================

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

# -----------------------------------------------------------------------------
# 업종별 자동 선택 기준
# -----------------------------------------------------------------------------
COVERAGE_TH = 0.20      # 업종 내 20% 이상 기업에서 발생
INTENSITY_TH = 0.005    # 매출 대비 중앙값(|amount|/revenue) ≥ 0.5%

# -----------------------------------------------------------------------------
# 운영 CAPEX 후보 (Owner Earnings 차감 대상)
# -----------------------------------------------------------------------------
OPERATING_COLS = [
    "inv_ppe_acq",
    "inv_intang_acq",
    "inv_cip",
    "inv_facility",
    "inv_equipment",
    "inv_software",
    "inv_dev_cost",
]

# -----------------------------------------------------------------------------
# 확장 투자 후보 (참고/리포트용)
# -----------------------------------------------------------------------------
EXPANDED_COLS = OPERATING_COLS + [
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

# -----------------------------------------------------------------------------
# DuckDB 연결 및 SQLite ATTACH
# -----------------------------------------------------------------------------
con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

print("▶ 업종별 CAPEX 자동 선택 cash mart 재생성 시작")

# -----------------------------------------------------------------------------
# 필수 테이블 확인
# -----------------------------------------------------------------------------
if not table_exists(con, "mart_financial_base"):
    raise RuntimeError("mart_financial_base 테이블이 없습니다.")

try:
    con.execute("SELECT induty_code FROM sdb.dim_company LIMIT 1")
except Exception:
    raise RuntimeError("SQLite dim_company.induty_code 컬럼이 없습니다.")

# -----------------------------------------------------------------------------
# 1) 연간 Wide 테이블 생성 (reprt_code = '11011')
# -----------------------------------------------------------------------------
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

    SUM(CASE WHEN account_std = 'CFO'           THEN amount END) AS cfo,
    SUM(CASE WHEN account_std = 'NET_INCOME'    THEN amount END) AS net_income,
    SUM(CASE WHEN account_std = 'DEPRECIATION'  THEN amount END) AS depreciation,
    SUM(CASE WHEN account_std = 'REVENUE'       THEN amount END) AS revenue,

    SUM(CASE WHEN account_std = 'INV_PPE_ACQ'       THEN amount END) AS inv_ppe_acq,
    SUM(CASE WHEN account_std = 'INV_INTANG_ACQ'    THEN amount END) AS inv_intang_acq,
    SUM(CASE WHEN account_std = 'INV_CIP'           THEN amount END) AS inv_cip,
    SUM(CASE WHEN account_std = 'INV_FACILITY'      THEN amount END) AS inv_facility,
    SUM(CASE WHEN account_std = 'INV_EQUIPMENT'     THEN amount END) AS inv_equipment,
    SUM(CASE WHEN account_std = 'INV_SOFTWARE'      THEN amount END) AS inv_software,
    SUM(CASE WHEN account_std = 'INV_DEV_COST'      THEN amount END) AS inv_dev_cost,

    SUM(CASE WHEN account_std = 'INV_SUBSIDIARY_ACQ' THEN amount END) AS inv_subsidiary_acq,
    SUM(CASE WHEN account_std = 'INV_BUSINESS_ACQ'   THEN amount END) AS inv_business_acq,
    SUM(CASE WHEN account_std = 'INV_ASSOCIATE'      THEN amount END) AS inv_associate,
    SUM(CASE WHEN account_std = 'INV_EQUITY_INVEST'  THEN amount END) AS inv_equity_invest,
    SUM(CASE WHEN account_std = 'INV_SECURITIES'     THEN amount END) AS inv_securities,
    SUM(CASE WHEN account_std = 'INV_FIN_ASSET'      THEN amount END) AS inv_fin_asset,
    SUM(CASE WHEN account_std = 'INV_LOANS'          THEN amount END) AS inv_loans

  FROM base
  GROUP BY 1,2,3,4
)
SELECT * FROM agg;
""")

# -----------------------------------------------------------------------------
# 2) 업종별 CAPEX 선택 정책 계산 (coverage + median intensity)
# -----------------------------------------------------------------------------
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
      CASE
        WHEN revenue IS NOT NULL AND revenue != 0
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

# -----------------------------------------------------------------------------
# 3) 정책 적용하여 mart_buffett_cash_annual 재생성
# -----------------------------------------------------------------------------
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
)

SELECT
  w.corp_code,
  w.bsns_year,
  w.fs_div,
  w.induty_code,

  w.cfo,
  w.net_income,
  w.depreciation,
  w.revenue,

  (
    (CASE WHEN COALESCE(f.use_inv_ppe_acq,0)=1    THEN COALESCE(w.inv_ppe_acq,0)    ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_intang_acq,0)=1 THEN COALESCE(w.inv_intang_acq,0) ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_cip,0)=1        THEN COALESCE(w.inv_cip,0)        ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_facility,0)=1   THEN COALESCE(w.inv_facility,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_equipment,0)=1  THEN COALESCE(w.inv_equipment,0)  ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_software,0)=1   THEN COALESCE(w.inv_software,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_dev_cost,0)=1   THEN COALESCE(w.inv_dev_cost,0)   ELSE 0 END)
  ) AS capex_total,

  (
    COALESCE(w.inv_ppe_acq,0) + COALESCE(w.inv_intang_acq,0) + COALESCE(w.inv_cip,0) +
    COALESCE(w.inv_facility,0) + COALESCE(w.inv_equipment,0) + COALESCE(w.inv_software,0) +
    COALESCE(w.inv_dev_cost,0) +
    COALESCE(w.inv_subsidiary_acq,0) + COALESCE(w.inv_business_acq,0) +
    COALESCE(w.inv_associate,0) + COALESCE(w.inv_equity_invest,0) +
    COALESCE(w.inv_securities,0) + COALESCE(w.inv_fin_asset,0) + COALESCE(w.inv_loans,0)
  ) AS invest_total,

  w.cfo -
  (
    (CASE WHEN COALESCE(f.use_inv_ppe_acq,0)=1    THEN COALESCE(w.inv_ppe_acq,0)    ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_intang_acq,0)=1 THEN COALESCE(w.inv_intang_acq,0) ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_cip,0)=1        THEN COALESCE(w.inv_cip,0)        ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_facility,0)=1   THEN COALESCE(w.inv_facility,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_equipment,0)=1  THEN COALESCE(w.inv_equipment,0)  ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_software,0)=1   THEN COALESCE(w.inv_software,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_dev_cost,0)=1   THEN COALESCE(w.inv_dev_cost,0)   ELSE 0 END)
  ) AS free_cash_flow,

  w.net_income + COALESCE(w.depreciation,0) -
  (
    (CASE WHEN COALESCE(f.use_inv_ppe_acq,0)=1    THEN COALESCE(w.inv_ppe_acq,0)    ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_intang_acq,0)=1 THEN COALESCE(w.inv_intang_acq,0) ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_cip,0)=1        THEN COALESCE(w.inv_cip,0)        ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_facility,0)=1   THEN COALESCE(w.inv_facility,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_equipment,0)=1  THEN COALESCE(w.inv_equipment,0)  ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_software,0)=1   THEN COALESCE(w.inv_software,0)   ELSE 0 END) +
    (CASE WHEN COALESCE(f.use_inv_dev_cost,0)=1   THEN COALESCE(w.inv_dev_cost,0)   ELSE 0 END)
  ) AS owner_earnings

FROM w
LEFT JOIN flags f
  ON w.induty_code = f.induty_code;
""")

row_cnt = con.execute("SELECT COUNT(*) FROM mart_buffett_cash_annual").fetchone()[0]
print(f"✅ mart_buffett_cash_annual 재생성 완료: {row_cnt:,} rows")

con.close()

print("\n👉 다음 단계 실행:")
print("   python scripts/08_4_build_buffett_earning_power_10y.py")
print("   python scripts/09_6_build_yearly_scores.py")
print("   python scripts/10_3_batch_top20_html_reports.py")
