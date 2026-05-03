"""
02_init_db.py

역할:
- SQLite DB 스키마 초기화
- 테이블 생성만 담당 (데이터 insert ❌)

실행:
python scripts/02_init_db.py
"""

from sqlalchemy import create_engine, text

DB_PATH = "sqlite:///data/opendart.sqlite"
engine = create_engine(DB_PATH)

with engine.begin() as conn:

    # -------------------------------------------------
    # 1. 회사 마스터
    # -------------------------------------------------
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS dim_company (
        corp_code TEXT PRIMARY KEY,   -- 8자리 고유번호
        stock_code TEXT,              -- 6자리 종목코드 (상장사)
        corp_name TEXT NOT NULL,
        market TEXT,                  -- KOSPI / KOSDAQ (추후 확장)
        modify_date TEXT
    );
    """))

    # -------------------------------------------------
    # 2. 공시 메타 정보 (list.json 결과)
    # -------------------------------------------------
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS fact_filing (
        rcept_no   TEXT PRIMARY KEY,  -- 접수번호(14자리)
        corp_code  TEXT NOT NULL,
        corp_name  TEXT,
        stock_code TEXT,
        corp_cls   TEXT,              -- Y/K/N/E
        report_nm  TEXT,
        flr_nm     TEXT,
        rcept_dt   TEXT,              -- YYYYMMDD
        rm         TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """))

    # 인덱스 (조회 성능)
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_filing_corp_code
        ON fact_filing(corp_code);
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_filing_rcept_dt
        ON fact_filing(rcept_dt);
    """))

    # -------------------------------------------------
    # 3. 재무제표 (정규화 핵심 테이블)
    # -------------------------------------------------
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS fact_financial_statement (
        corp_code  TEXT,          -- 회사 고유번호
        bsns_year  INTEGER,       -- 사업연도
        reprt_code TEXT,          -- 11011(사업),11012(반기),11013(1Q),11014(3Q)
        fs_div     TEXT,          -- CFS(연결) / OFS(별도)
        sj_div     TEXT,          -- BS / IS / CF
        account_nm TEXT,          -- 계정명
        amount     REAL,          -- 금액 (당기)
        PRIMARY KEY (
            corp_code,
            bsns_year,
            reprt_code,
            fs_div,
            sj_div,
            account_nm
        )
    );
    """))

    # -------------------------------------------------
    # 4. ETL Job Queue (재무제표 백필용)
    # -------------------------------------------------
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS etl_job_financial (
        corp_code   TEXT,
        bsns_year   INTEGER,
        reprt_code  TEXT,
        fs_div      TEXT,
        status      TEXT DEFAULT 'PENDING',  -- PENDING/DONE/NO_DATA/FAILED
        last_error  TEXT,
        retry_cnt   INTEGER DEFAULT 0,
        updated_at  TEXT,
        PRIMARY KEY (corp_code, bsns_year, reprt_code, fs_div)
    );
    """))
    
    # -------------------------------------------------
    # 5. 일일 API 쿼터 관리
    # -------------------------------------------------
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS etl_quota_daily (
        run_date        TEXT PRIMARY KEY,   -- YYYYMMDD
        used_requests   INTEGER DEFAULT 0,
        limit_requests  INTEGER
    );
    """))


print("✅ SQLite DB schema initialized (STEP 7 기준)")