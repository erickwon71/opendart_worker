import duckdb
import pandas as pd
import sqlite3

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

def main():
    con = duckdb.connect(DUCKDB_PATH)
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

    print("▶ 단위 정규화(Unit Normalization) 자동 보정 시작")

    # 1) 업종별 매출/자산 비율(Asset Turnover) 중앙값 계산
    # mart_metrics_annual을 활용하여 통계 산출
    con.execute("""
    CREATE OR REPLACE TABLE dim_industry_turnover_stats AS
    SELECT 
        induty_code,
        median(revenue / assets) as median_turnover
    FROM mart_metrics_annual m
    LEFT JOIN sdb.dim_company dc ON m.corp_code = dc.corp_code
    WHERE assets > 0 AND revenue > 0
    GROUP BY induty_code;
    """)

    # 2) 보정 대상 식별
    # 중앙값 대비 500배 이상 크거나 1/500 이하인 경우 (10^3 단위 오차 감지)
    con.execute("""
    CREATE OR REPLACE TABLE tmp_unit_correction_candidates AS
    SELECT 
        m.corp_code, m.bsns_year, m.revenue, m.assets,
        (m.revenue / m.assets) as current_turnover,
        s.median_turnover,
        CASE 
            WHEN (m.revenue / m.assets) / s.median_turnover > 500 THEN 0.001
            WHEN (m.revenue / m.assets) / s.median_turnover < 0.002 THEN 1000.0
            -- 경 단위 데이터(e15 이상)는 무조건 10^6 이상 보정 시도
            WHEN m.revenue > 1e15 THEN 0.000001
            ELSE 1.0
        END as correction_factor
    FROM mart_metrics_annual m
    LEFT JOIN sdb.dim_company dc ON m.corp_code = dc.corp_code
    LEFT JOIN dim_industry_turnover_stats s ON dc.induty_code = s.induty_code
    WHERE correction_factor != 1.0;
    """)

    # 3) 보정 이력 저장 (SQLite dim_unit_correction)
    con.execute("""
    CREATE TABLE IF NOT EXISTS sdb.dim_unit_correction (
        corp_code TEXT,
        bsns_year INTEGER,
        correction_factor REAL,
        reason TEXT,
        updated_at TEXT
    );
    """)

    # 신규 보정 건만 삽입
    con.execute("""
    INSERT INTO sdb.dim_unit_correction
    SELECT corp_code, bsns_year, correction_factor, 'Statistically Outlier', CAST(current_timestamp AS TEXT)
    FROM tmp_unit_correction_candidates c
    WHERE NOT EXISTS (
        SELECT 1 FROM sdb.dim_unit_correction 
        WHERE corp_code = c.corp_code AND bsns_year = c.bsns_year
    );
    """)

    # 4) mart_financial_base에 보정 적용 (정규화된 테이블 생성)
    con.execute("""
    CREATE OR REPLACE TABLE mart_financial_base AS
    SELECT 
        f.corp_code, f.bsns_year, f.reprt_code, f.fs_div, f.sj_div, f.account_nm, f.account_std,
        f.amount * COALESCE(u.correction_factor, 1.0) as amount
    FROM mart_financial_base f
    LEFT JOIN sdb.dim_unit_correction u 
      ON f.corp_code = u.corp_code AND f.bsns_year = u.bsns_year;
    """)

    # 결과 확인
    cnt = con.execute("SELECT COUNT(*) FROM tmp_unit_correction_candidates").fetchone()[0]
    print(f"✅ 단위 보정 적용 완료: {cnt}건의 기업/연도 데이터 보정됨")
    
    if cnt > 0:
        print("\n - 보정 샘플:")
        print(con.execute("SELECT corp_code, bsns_year, correction_factor FROM tmp_unit_correction_candidates LIMIT 5").df())

    con.close()

if __name__ == "__main__":
    main()
