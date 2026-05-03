"""
06_run_financial_worker.py (완성본)

Job Queue(etl_job_financial)를 기반으로 OpenDART fnlttSinglAcntAll.json을 호출하여
하루 API 한도 내에서 재무 데이터를 수집한다.

- macOS + LibreSSL 환경에서 urllib3<2 권장 (안정성)
- requests Session + Retry (네트워크 끊김/일시 오류 흡수)
- Job 단위 try/except로 Worker 전체 크래시 방지
- status=020(요청 제한 초과)이면 즉시 종료
- status=013(데이터 없음)은 NO_DATA로 정상 처리

API 스펙(요청 인자/보고서 코드/fs_div/응답 status 등):
- GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json
- bsns_year: 2015년 이후 제공
- reprt_code: 11011(사업),11012(반기),11013(1Q),11014(3Q)
- fs_div: CFS(연결), OFS(별도)
- status: 000 정상, 013 데이터 없음, 020 요청 제한 초과 등
(출처: OpenDART 개발가이드) [2](https://futureseed.tistory.com/76)
"""

import os
import json
import time
import random
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# -----------------------------
# 운영 파라미터
# -----------------------------
DAILY_LIMIT = 40000          # 사용자 기준
SAFE_RATIO  = 0.95           # 일일 한도 90%까지만 사용 (안전 마진)
BATCH_COMMIT_EVERY_JOBS = 50 # DB commit 빈도 (너무 잦으면 느려짐)
SLEEP_JITTER = (0.05, 0.20)  # 요청 간 미세 지터(서버 보호/리셋 완화)


BASE_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"


# -----------------------------
# 유틸
# -----------------------------
def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")

def safe_float(x):
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "null":
        return None
    # 콤마 제거 가능성 대비
    s = s.replace(",", "")
    try:
        return float(s)
    except:
        return None

def make_session() -> requests.Session:
    """
    네트워크 끊김/일시 장애를 흡수하기 위한 Session + Retry
    - HTTP 상태코드 기반 재시도 (429, 5xx)
    - connect/read 재시도 포함
    """
    s = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# -----------------------------
# DB 관련
# -----------------------------
def ensure_today_quota(cur, run_date: str):
    cur.execute("""
    INSERT OR IGNORE INTO etl_quota_daily (run_date, used_requests, limit_requests)
    VALUES (?, 0, ?)
    """, (run_date, DAILY_LIMIT))

def get_today_quota(cur, run_date: str):
    cur.execute("""
    SELECT used_requests, limit_requests
    FROM etl_quota_daily
    WHERE run_date = ?
    """, (run_date,))
    row = cur.fetchone()
    if not row:
        return 0, DAILY_LIMIT
    return int(row[0]), int(row[1])

def set_today_used(cur, run_date: str, used: int):
    cur.execute("""
    UPDATE etl_quota_daily
    SET used_requests = ?
    WHERE run_date = ?
    """, (used, run_date))

def fetch_next_job(cur):
    cur.execute("""
    SELECT corp_code, bsns_year, reprt_code, fs_div
    FROM etl_job_financial
    WHERE status='PENDING'
    LIMIT 1
    """)
    return cur.fetchone()

def update_job(cur, corp_code, year, reprt, fs_div, status, last_error=None):
    cur.execute("""
    UPDATE etl_job_financial
    SET status=?, last_error=?, retry_cnt=CASE WHEN ?='FAILED' THEN retry_cnt+1 ELSE retry_cnt END,
        updated_at=?
    WHERE corp_code=? AND bsns_year=? AND reprt_code=? AND fs_div=?
    """, (status, last_error, status, today_yyyymmdd(), corp_code, year, reprt, fs_div))


# -----------------------------
# 메인
# -----------------------------
def main():
    load_dotenv()
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise RuntimeError("DART_API_KEY not found in .env")

    run_date = today_yyyymmdd()
    session = make_session()

    conn = sqlite3.connect("data/opendart.sqlite")
    cur = conn.cursor()

    ensure_today_quota(cur, run_date)
    conn.commit()

    used, limit_req = get_today_quota(cur, run_date)
    max_today = int(limit_req * SAFE_RATIO)

    print(f"🔹 run_date={run_date} | used={used:,} / max_today={max_today:,} (limit={limit_req:,})")

    jobs_done = 0
    jobs_nodata = 0
    jobs_failed = 0
    rows_inserted = 0

    # insert 멱등(Primary Key + OR IGNORE)
    insert_sql = """
    INSERT OR IGNORE INTO fact_financial_statement
    (corp_code, bsns_year, reprt_code, fs_div, sj_div, account_nm, amount)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    while used < max_today:
        job = fetch_next_job(cur)
        if not job:
            print("✅ PENDING job 없음 → 오늘 작업 종료")
            break

        corp_code, year, reprt, fs_div = job

        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": str(reprt),
            "fs_div": str(fs_div),
        }

        # 요청 간 지터 (서버 보호 및 reset 완화)
        time.sleep(random.uniform(*SLEEP_JITTER))

        used += 1  # 호출 시도 자체를 사용량으로 카운트 (보수적으로 관리)

        try:
            resp = session.get(BASE_URL, params=params, timeout=30)
            # JSON 파싱
            try:
                data = resp.json()
            except Exception:
                # JSON이 아닐 수 있음(점검/오류 시 XML/HTML 등)
                update_job(cur, corp_code, year, reprt, fs_div, "FAILED",
                           last_error=f"Non-JSON response (HTTP {resp.status_code})")
                jobs_failed += 1
                continue

            status = data.get("status")
            message = data.get("message")

            # OpenDART: 000 정상, 013 데이터 없음, 020 제한 초과 등 [2](https://futureseed.tistory.com/76)
            if status == "000":
                items = data.get("list", [])
                payload = []
                for it in items:
                    payload.append((
                        corp_code,
                        int(year),
                        str(reprt),
                        str(fs_div),
                        it.get("sj_div"),            # BS/IS/CIS/CF/SCE [2](https://futureseed.tistory.com/76)
                        it.get("account_nm"),
                        safe_float(it.get("thstrm_amount")),  # 당기금액 [2](https://futureseed.tistory.com/76)
                    ))

                if payload:
                    cur.executemany(insert_sql, payload)
                    rows_inserted += len(payload)

                update_job(cur, corp_code, year, reprt, fs_div, "DONE", last_error=None)
                jobs_done += 1

            elif status == "013":
                # 데이터 없음(정상 케이스)
                update_job(cur, corp_code, year, reprt, fs_div, "NO_DATA", last_error=message)
                jobs_nodata += 1

            elif status == "020":
                # 요청 제한 초과 → 즉시 중단 [2](https://futureseed.tistory.com/76)
                update_job(cur, corp_code, year, reprt, fs_div, "FAILED", last_error=f"{status}:{message}")
                jobs_failed += 1
                print("⛔ status=020 (요청 제한 초과) → 오늘 즉시 종료")
                break

            else:
                update_job(cur, corp_code, year, reprt, fs_div, "FAILED", last_error=f"{status}:{message}")
                jobs_failed += 1

        except requests.exceptions.RequestException as e:
            # ConnectionResetError 포함한 네트워크/타임아웃 오류가 여기로 옴
            update_job(cur, corp_code, year, reprt, fs_div, "FAILED", last_error=str(e))
            jobs_failed += 1
            # 다음 job으로 계속
            continue

        # quota 저장
        set_today_used(cur, run_date, used)

        # 주기적으로 commit
        if (jobs_done + jobs_nodata + jobs_failed) % BATCH_COMMIT_EVERY_JOBS == 0:
            conn.commit()
            print(f"… progress jobs={jobs_done+jobs_nodata+jobs_failed:,} | "
                  f"DONE={jobs_done:,} NO_DATA={jobs_nodata:,} FAILED={jobs_failed:,} | "
                  f"rows={rows_inserted:,} | used={used:,}/{max_today:,}")

    # 마지막 commit
    set_today_used(cur, run_date, used)
    conn.commit()
    conn.close()

    print("--------------------------------------------------")
    print(f"✅ 오늘 처리 Job 합계 : {jobs_done+jobs_nodata+jobs_failed:,}")
    print(f"   - DONE    : {jobs_done:,}")
    print(f"   - NO_DATA : {jobs_nodata:,}")
    print(f"   - FAILED  : {jobs_failed:,}")
    print(f"✅ 저장된 재무 레코드(이번 실행) : {rows_inserted:,}")
    print(f"✅ 오늘 API 사용량 used_requests : {used:,} / max_today={max_today:,} (limit={limit_req:,})")
    print("✅ Worker 종료")


if __name__ == "__main__":
    main()