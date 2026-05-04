import duckdb
import pandas as pd

DUCKDB_PATH = "data/analytics.duckdb"

def check_data_integrity():
    con = duckdb.connect(DUCKDB_PATH)
    
    print("=== 데이터 정합성 점검 (Unit Error & Missing Values) ===")
    
    # 1. 지표별 결측치 비율 확인
    print("\n1. 지표별 결측치 현황:")
    null_stats = con.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(revenue) as revenue_cnt,
            COUNT(roe) as roe_cnt,
            COUNT(opm) as opm_cnt,
            COUNT(assets) as assets_cnt
        FROM mart_metrics_annual
    """).df()
    print(null_stats)

    # 2. 단위 오류(Unit Error) 의심 사례 탐색
    # 자산이 너무 작거나 (예: 100만원 미만), 매출/자산 비율이 비정상적인 경우
    print("\n2. 단위 오류 의심 사례 (자산 < 100만 원):")
    unit_errors = con.execute("""
        SELECT corp_code, bsns_year, assets, revenue
        FROM mart_metrics_annual
        WHERE assets > 0 AND assets < 1000000
        LIMIT 10
    """).df()
    print(unit_errors)

    # 3. 비정상적 수익성 지표 (ROE > 200% 등)
    print("\n3. 비정상 수익성 지표 (ROE > 200%):")
    extreme_roe = con.execute("""
        SELECT corp_code, bsns_year, roe, net_income, equity
        FROM mart_metrics_annual
        WHERE roe > 2.0
        ORDER BY roe DESC
        LIMIT 10
    """).df()
    print(extreme_roe)

    # 4. 현금흐름 괴리 (순이익 대비 영업현금흐름)
    # 08_3에서 생성된 mart_buffett_cash_annual 활용
    print("\n4. 이익의 질 점검 (순이익 vs 영업현금흐름 괴리):")
    cf_mismatch = con.execute("""
        SELECT corp_code, bsns_year, net_income, cfo, (cfo - net_income) as gap
        FROM mart_buffett_cash_annual
        WHERE net_income > 1000000000 -- 10억 이상인 경우만
          AND cfo < 0
        ORDER BY gap ASC
        LIMIT 10
    """).df()
    print(cf_mismatch)

    con.close()

if __name__ == "__main__":
    check_data_integrity()
