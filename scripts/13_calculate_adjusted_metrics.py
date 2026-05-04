import duckdb
import pandas as pd

DUCKDB_PATH = "data/analytics.duckdb"

# --------------------------------------------------
# 비경상(일회성) 항목 정의
# --------------------------------------------------
NON_RECURRING_PATTERNS = {
    "gain_disposal": ["%유형자산처분이익%", "%무형자산처분이익%", "%투자부동산처분이익%", "%계열회사주식처분이익%"],
    "loss_disposal": ["%유형자산처분손실%", "%무형자산처분손실%", "%투자부동산처분손실%"],
    "impairment": ["%손상차손%", "%영업권손상차손%"],
    "valuation": ["%평가이익%", "%평가손실%"], # 단기금융상품 등은 일회성으로 간주할지 고민이나 일단 포함
    "misc": ["%잡이익%", "%잡손실%", "%재해손실%"]
}

def main():
    con = duckdb.connect(DUCKDB_PATH)
    
    print("▶ 비경상 손익 항목 식별 및 조정 이익 산출 시작")

    # 1) 비경상 항목 합계 산출 (각 기업/연도별)
    con.execute("""
    CREATE OR REPLACE TABLE tmp_non_recurring AS
    SELECT 
        corp_code, bsns_year, fs_div,
        SUM(CASE 
            WHEN account_nm ILIKE '%처분이익%' 
              OR account_nm ILIKE '%환입%' 
              OR account_nm ILIKE '%평가이익%' 
              OR account_nm ILIKE '%잡이익%' 
            THEN amount ELSE 0 END) as non_recurring_gain,
        SUM(CASE 
            WHEN account_nm ILIKE '%처분손실%' 
              OR account_nm ILIKE '%손상차손%' 
              OR account_nm ILIKE '%평가손실%' 
              OR account_nm ILIKE '%잡손실%' 
              OR account_nm ILIKE '%재해손실%' 
            THEN amount ELSE 0 END) as non_recurring_loss
    FROM mart_financial_base
    WHERE sj_div IN ('IS', 'CIS') -- 손익계산서 항목만
    GROUP BY 1, 2, 3;
    """)

    # 2) mart_metrics_annual과 결합하여 Adjusted Net Income 산출
    # Adjusted Net Income = Net Income - (non_recurring_gain - non_recurring_loss)
    # (세후 효과를 고려해야 하지만, 일단 단순화를 위해 세전으로 처리하거나 0.75 정도의 계수를 곱할 수 있음)
    TAX_RATE = 0.22 

    con.execute(f"""
    CREATE OR REPLACE TABLE mart_adjusted_metrics AS
    SELECT 
        m.*,
        n.non_recurring_gain,
        n.non_recurring_loss,
        (n.non_recurring_gain + n.non_recurring_loss) as net_non_recurring, -- loss는 이미 음수로 들어가 있을 확률이 높음 (확인 필요)
        m.net_income - ((COALESCE(n.non_recurring_gain,0) + COALESCE(n.non_recurring_loss,0)) * (1 - {TAX_RATE})) as adj_net_income
    FROM mart_metrics_annual m
    LEFT JOIN tmp_non_recurring n
      ON m.corp_code = n.corp_code AND m.bsns_year = n.bsns_year AND m.fs_div = n.fs_div;
    """)

    # 검증: 조정 전후 순이익 차이 확인
    print("\n✅ 조정 이익 산출 완료 (mart_adjusted_metrics)")
    sample = con.execute("""
        SELECT corp_code, bsns_year, net_income, adj_net_income 
        FROM mart_adjusted_metrics 
        WHERE ABS(net_income - adj_net_income) > 1000000000 
        LIMIT 5
    """).df()
    print(" - 조정액 10억 이상 샘플:")
    print(sample)

    con.close()

if __name__ == "__main__":
    main()
