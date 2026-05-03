import os
import time
import sqlite3
import requests
from dotenv import load_dotenv

# =============================================================================
# OpenDART 기업개황(company.json) 기반 업종코드(induty_code) 백필
#
# 정책 (최종):
# - 000 : 정상 처리
# - 013 : skip
# - 020 : 즉시 종료 (sleep 없음, launchd 안전)
# - 기타: 즉시 오류 종료
# =============================================================================

DB_PATH = "data/opendart.sqlite"
API_URL = "https://opendart.fss.or.kr/api/company.json"

MAX_CALLS_PER_RUN = 2500
SLEEP_NORMAL = 0.12
TIMEOUT = 20

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
if not API_KEY:
    raise SystemExit("❌ DART_API_KEY가 .env에 없습니다.")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 컬럼 확인
cur.execute("PRAGMA table_info(dim_company)")
cols = [r[1] for r in cur.fetchall()]
if "induty_code" not in cols:
    cur.execute("ALTER TABLE dim_company ADD COLUMN induty_code TEXT")
    conn.commit()
    print("✅ dim_company.induty_code 컬럼 추가 완료")

# 대상 기업 (재무데이터 있는 기업 + induty_code 미설정)
cur.execute("""
SELECT DISTINCT d.corp_code
FROM dim_company d
JOIN fact_financial_statement f
  ON d.corp_code = f.corp_code
WHERE d.induty_code IS NULL OR d.induty_code = ''
""")
targets = [r[0] for r in cur.fetchall()]
print(f"▶ 업종코드 백필 대상 기업 수: {len(targets):,}")

called = 0
updated = 0
skipped_013 = 0

for corp_code in targets:
    if called >= MAX_CALLS_PER_RUN:
        print(f"⏹ MAX_CALLS_PER_RUN({MAX_CALLS_PER_RUN}) 도달 → 정상 종료")
        break

    try:
        resp = requests.get(
            API_URL,
            params={"crtfc_key": API_KEY, "corp_code": corp_code},
            timeout=TIMEOUT,
        )
        data = resp.json()
    except Exception as e:
        conn.commit()
        conn.close()
        raise SystemExit(f"❌ API 호출/파싱 오류: {e}")

    status = data.get("status")
    message = data.get("message", "")

    if status == "000":
        induty_code = data.get("induty_code")
        if induty_code:
            cur.execute(
                "UPDATE dim_company SET induty_code=? WHERE corp_code=?",
                (induty_code, corp_code),
            )
            updated += 1

    elif status == "013":
        skipped_013 += 1

    elif status == "020":
        conn.commit()
        conn.close()
        print("🚨 OpenDART 요청 제한 초과(status=020)")
        print("✅ 즉시 종료합니다. (내일 재실행 권장)")
        raise SystemExit(3)

    else:
        conn.commit()
        conn.close()
        raise SystemExit(f"❌ OpenDART API 오류(status={status}): {message}")

    called += 1

    if called % 100 == 0:
        conn.commit()
        print(f"… 진행 {called}/{MAX_CALLS_PER_RUN} | 업데이트 {updated} | 013 스킵 {skipped_013}")

    time.sleep(SLEEP_NORMAL)

conn.commit()
conn.close()

print("\n✅ 업종코드 백필 정상 완료")
print(f"   호출 수  : {called}")
print(f"   업데이트 : {updated}")
print(f"   013 스킵 : {skipped_013}")
