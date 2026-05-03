import os
import argparse
import pandas as pd
import duckdb
import matplotlib.pyplot as plt
from jinja2 import Template
from base64 import b64encode
from io import BytesIO

DUCKDB_PATH = "data/analytics.duckdb"
SQLITE_PATH = "data/opendart.sqlite"

parser = argparse.ArgumentParser()
parser.add_argument("--corp_code", required=True)
parser.add_argument("--fs_div", default="CFS", choices=["CFS","OFS"])
parser.add_argument("--years", type=int, default=10)
args = parser.parse_args()

corp_code = args.corp_code
fs_div = args.fs_div
years = args.years

# DB 연결
con = duckdb.connect(DUCKDB_PATH)
con.execute("INSTALL sqlite;")
con.execute("LOAD sqlite;")
con.execute(f"ATTACH '{SQLITE_PATH}' AS sdb (TYPE SQLITE);")

corp_name = con.execute("""
SELECT corp_name FROM sdb.dim_company WHERE corp_code=?
""", [corp_code]).fetchone()
corp_name = corp_name[0] if corp_name else corp_code

# ------------------ 연도별 데이터 ------------------
df = con.execute("""
WITH y AS (
  SELECT *
  FROM mart_score_combined_yearly
  WHERE corp_code=? AND fs_div=?
  ORDER BY bsns_year DESC
  LIMIT ?
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
),
j AS (
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
)
SELECT * FROM j ORDER BY bsns_year
""", [corp_code, fs_div, years, corp_code, fs_div, corp_code, fs_div]).df()

if len(df) < 5:
    raise SystemExit("5년 미만 데이터로 HTML 리포트 생성 불가")

# ------------------ 요약문 ------------------
summary = con.execute("""
SELECT earning_power_summary
FROM (
  SELECT *,
         '본 기업은 ' || start_year || '~' || end_year || '년 동안 '
         || years_used || '년치 데이터 기준 평균 Owner Earnings '
         || printf('%,.0f', avg_owner_earnings)
         || '을 기록했으며, 양(+)의 Owner Earnings 비율은 '
         || ROUND(positive_owner_ratio*100,0)
         || '%이다. 평균 FCF 마진은 '
         || ROUND(avg_fcf_margin*100,1)
         || '%로 장기적으로 현금 창출력이 '
         || CASE WHEN avg_fcf_margin > 0.1 THEN '우수하다.'
                 ELSE '제한적이다.' END
         AS earning_power_summary
  FROM mart_buffett_earning_power_10y
  WHERE corp_code=? AND fs_div=?
)
""", [corp_code, fs_div]).fetchone()[0]

# ------------------ 그래프 생성 ------------------
plt.figure(figsize=(12,7))
plt.plot(df["bsns_year"], df["combined_score"], marker="o", label="Combined Score")
plt.plot(df["bsns_year"], df["total_score"], marker="o", label="Quality Score")
plt.plot(df["bsns_year"], df["buffett_total_score"], marker="o", label="Buffett Score")
plt.title("Score Trend")
plt.xlabel("Year")
plt.ylabel("Score")
plt.grid(True, alpha=0.3)
plt.legend()

buf = BytesIO()
plt.savefig(buf, format="png", dpi=150)
plt.close()
img_base64 = b64encode(buf.getvalue()).decode("utf-8")

# ------------------ HTML 생성 ------------------
html_template = Template("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{{ corp_name }} Earning Power Report</title>
<style>
body { font-family: Arial; margin: 40px; }
h1 { color: #2c3e50; }
table { border-collapse: collapse; margin-top: 20px; }
th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: right; }
th { background-color: #f2f2f2; }
td:first-child, th:first-child { text-align: center; }
.summary { margin-top: 20px; font-size: 15px; }
</style>
</head>
<body>

<h1>{{ corp_name }} ({{ corp_code }}) – Earning Power Report</h1>
<p><b>재무구분:</b> {{ fs_div }}</p>

<div class="summary">
<b>요약:</b><br/>
{{ summary }}
</div>

<h2>① 10년 점수 추이</h2>
<img src="data:image/png;base64,{{ img }}" width="800"/>

<h2>② 연도별 상세 데이터</h2>
<table>
<tr>
{% for col in df.columns %}
<th>{{ col }}</th>
{% endfor %}
</tr>
{% for row in df.values %}
<tr>
{% for v in row %}
<td>{{ "%.3f"|format(v) if v is number else v }}</td>
{% endfor %}
</tr>
{% endfor %}
</table>

</body>
</html>
""")

html = html_template.render(
    corp_name=corp_name,
    corp_code=corp_code,
    fs_div=fs_div,
    summary=summary,
    img=img_base64,
    df=df
)

out_dir = "output/company_reports"
os.makedirs(out_dir, exist_ok=True)
html_path = os.path.join(out_dir, f"{corp_code}_{fs_div}_earning_power.html")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

con.close()

print("✅ HTML Earning Power 리포트 생성 완료")
print(f"📄 파일: {html_path}")