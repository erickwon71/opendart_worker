import os
import argparse
import pandas as pd
import duckdb
import matplotlib.pyplot as plt

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

parser = argparse.ArgumentParser()
parser.add_argument("--corp_code", type=str, default=None)
parser.add_argument("--corp_name", type=str, default=None)
parser.add_argument("--fs_div", type=str, default="CFS", choices=["CFS","OFS"])
parser.add_argument("--years", type=int, default=10)
args = parser.parse_args()

if not args.corp_code and not args.corp_name:
    raise SystemExit("corp_code 또는 corp_name 중 하나는 반드시 입력해야 합니다.")

con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

# corp_code 결정
corp_code = args.corp_code
if not corp_code:
    row = con.execute("""
      SELECT corp_code FROM sdb.dim_company
      WHERE corp_name = ?
      LIMIT 1
    """, [args.corp_name]).fetchone()
    if not row:
        raise SystemExit("해당 corp_name을 dim_company에서 찾지 못했습니다. 정확한 기업명인지 확인하세요.")
    corp_code = row[0]

corp_name = con.execute("""
  SELECT corp_name FROM sdb.dim_company WHERE corp_code=?
""", [corp_code]).fetchone()
corp_name = corp_name[0] if corp_name else ""

fs_div = args.fs_div
years = args.years

# 최근 N년 데이터 뽑기 (점수 + 핵심값)
df = con.execute("""
WITH y AS (
  SELECT *
  FROM mart_score_combined_yearly
  WHERE corp_code=? AND fs_div=?
),
q AS (
  SELECT bsns_year, roe, opm
  FROM mart_quality_score_yearly
  WHERE corp_code=? AND fs_div=?
),
b AS (
  SELECT bsns_year, owner_earnings, fcf_margin
  FROM mart_buffett_owner_score_yearly
  WHERE corp_code=? AND fs_div=?
)
SELECT
  y.bsns_year,
  y.total_score,
  y.buffett_total_score,
  y.combined_score,
  q.roe,
  q.opm,
  b.owner_earnings,
  b.fcf_margin
FROM y
LEFT JOIN q USING (bsns_year)
LEFT JOIN b USING (bsns_year)
ORDER BY bsns_year DESC
LIMIT ?
""", [corp_code, fs_div, corp_code, fs_div, corp_code, fs_div, years]).df()

if df.empty or len(df) < 5:
    raise SystemExit("해당 기업/재무구분에서 최소 5년치 데이터가 부족합니다(요구조건: 5년 미만 제외).")

df = df.sort_values("bsns_year")  # 차트용 오름차순

# 저장 경로
out_dir = "output/company_reports"
os.makedirs(out_dir, exist_ok=True)
csv_path = os.path.join(out_dir, f"{corp_code}_{fs_div}_{years}y.csv")
png_path = os.path.join(out_dir, f"{corp_code}_{fs_div}_{years}y.png")

# CSV 저장
df.to_csv(csv_path, index=False, encoding="utf-8-sig")

# ----------------- 차트 생성 -----------------
plt.figure(figsize=(14, 8))

# (1) 점수 추이
ax1 = plt.subplot(2,1,1)
ax1.plot(df["bsns_year"], df["total_score"], marker="o", label="Quality Score (total_score)")
ax1.plot(df["bsns_year"], df["buffett_total_score"], marker="o", label="Buffett Score (buffett_total_score)")
ax1.plot(df["bsns_year"], df["combined_score"], marker="o", label="Combined Score (0~1)")
ax1.set_title(f"{corp_name} ({corp_code}) [{fs_div}] - Scores Trend")
ax1.set_xlabel("Year")
ax1.set_ylabel("Score")
ax1.grid(True, alpha=0.3)
ax1.legend()

# (2) 핵심 값 추이
ax2 = plt.subplot(2,1,2)
ax2.plot(df["bsns_year"], df["roe"], marker="o", label="ROE")
ax2.plot(df["bsns_year"], df["opm"], marker="o", label="OPM")
ax2.plot(df["bsns_year"], df["fcf_margin"], marker="o", label="FCF Margin")
ax2.set_title("Key Financial Ratios Trend")
ax2.set_xlabel("Year")
ax2.set_ylabel("Ratio")
ax2.grid(True, alpha=0.3)
ax2.legend(loc="best")

plt.tight_layout()
plt.savefig(png_path, dpi=200)
plt.close()

con.close()

print("✅ 기업별 1페이지(표+차트) 리포트 생성 완료")
print(f"CSV: {csv_path}")
print(f"PNG: {png_path}")
