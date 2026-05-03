import os
import duckdb

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"
OUTPUT_DIR = "output"
OUTPUT_FILE = "earning_power_1page_report.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)

con = duckdb.connect(DUCKDB_PATH)

print("▶ STEP 11 기업별 1페이지 Earning Power 리포트 생성")

# SQLite(기업명) 연결
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)

con.execute(f"""
COPY (
  SELECT
    e.corp_code,
    dc.corp_name,
    e.fs_div,
    e.start_year || '~' || e.end_year        AS period,
    e.years_used,

    ROUND(e.avg_owner_earnings, 0)           AS avg_owner_earnings,
    ROUND(e.positive_owner_ratio, 2)         AS positive_owner_ratio,
    ROUND(e.avg_fcf_margin, 3)               AS avg_fcf_margin,
    ROUND(e.avg_capex_intensity, 3)          AS avg_capex_intensity,
    ROUND(e.avg_roe, 3)                      AS avg_roe,
    ROUND(e.std_roe, 3)                      AS std_roe,
    e.earning_power_score,

    (
      '본 기업은 ' || e.start_year || '~' || e.end_year || '년('
      || e.years_used || '년) 동안 평균 Owner Earnings '
      || printf('%,.0f', e.avg_owner_earnings) || '을 기록했으며, '
      || '전체 기간 중 ' || ROUND(e.positive_owner_ratio*100,0)
      || '% 연도에서 양(+)의 Owner Earnings를 유지했다. '
      || '평균 FCF 마진은 ' || ROUND(e.avg_fcf_margin*100,1)
      || '%, CAPEX/매출은 ' || ROUND(e.avg_capex_intensity*100,1)
      || '%로 자본집약도가 '
      || CASE WHEN e.avg_capex_intensity < 0.08 THEN '낮은 편이며, '
              WHEN e.avg_capex_intensity < 0.15 THEN '보통 수준이며, '
              ELSE '높은 편이며, ' END
      || 'ROE 평균 ' || ROUND(e.avg_roe*100,1)
      || '%, 변동성 ' || ROUND(e.std_roe*100,1)
      || '%p로 수익성의 '
      || CASE WHEN e.std_roe < 0.05 THEN '안정성이 높다.'
              WHEN e.std_roe < 0.10 THEN '안정적인 편이다.'
              ELSE '변동성이 존재한다.' END
    ) AS earning_power_summary

  FROM mart_buffett_earning_power_10y e
  LEFT JOIN sdb.dim_company dc
    ON e.corp_code = dc.corp_code
  ORDER BY e.earning_power_score DESC
)
TO '{output_path}'
WITH (HEADER, DELIMITER ',');
""")

con.close()

print("✅ 1페이지 Earning Power 리포트 생성 완료")
print(f"📄 파일 위치: {output_path}")