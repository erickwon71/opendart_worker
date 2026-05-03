# DART Finance Pipeline (dart_finance)

본 프로젝트는 금융감독원 OpenDART API 기반으로 상장사 재무 데이터를 수집/정제/분석(Mart)하고,  
Warren Buffett 스타일의 **Owner Earnings / FCF / 장기 Earning Power** 관점으로 기업을 스크리닝 및 리포트(HTML)까지 자동 생성하는 파이프라인이다.

---

## 0. 핵심 목표 (What we built)

- OpenDART 재무 데이터(재무상태표/손익/현금흐름)를 **SQLite에 저장**
- 계정명 변형을 흡수하기 위해 **표준계정(account_std) 매핑** 구축
- DuckDB로 분석용 Mart를 만들고, 지표(ROE/OPM/FCF/Owner Earnings) 계산
- CAPEX가 산업별로 다르게 표현되는 문제를 해결하기 위해  
  **업종(induty_code) 기반으로 CAPEX 구성 항목을 자동 선택**하여 `capex_total`을 계산
- 기업별
  - 단년도 스코어
  - 연도별(10년) 추세
  - 5~10년 장기 Earning Power 점수
  를 만들고
- Top 20 기업에 대해 **HTML 리포트(표+그래프)**를 자동 생성

---

## 1. 데이터 소스 & 핵심 개념

### 1.1 OpenDART 기업개황: 업종코드(induty_code)
업종코드는 OpenDART 기업개황(company.json)에 포함된다. [1](https://www.codestudy.net/blog/how-to-view-an-html-file-in-the-browser-with-visual-studio-code/)[2](https://code.visualstudio.com/docs/debugtest/integrated-browser)  
본 프로젝트는 이 업종코드를 사용해 **업종별 CAPEX 정의를 자동 분기**한다.

### 1.2 Buffett Owner Earnings (개념)
Owner Earnings는 Buffett이 1986년 Berkshire Hathaway 주주서한에서 언급한 개념으로,
회계 이익이 아니라 “주주가 꺼내 쓸 수 있는 실질 현금” 관점의 근사치다. [3](https://www.berkshirehathaway.com/letters/1986.html)[4](https://en.wikipedia.org/wiki/Owner_earnings)  
본 프로젝트에서는 다음과 같은 실무형 근사치를 사용한다:

- `FCF = CFO - capex_total`
- `Owner Earnings ≈ Net Income + Depreciation - capex_total`

(유지 CapEx 추정의 어려움이 있어 초기 단계는 `capex_total`을 보수적으로 적용)

---

## 2. 저장소 구조(데이터 레이어)

### 2.1 SQLite (원천 저장소: data/opendart.sqlite)
- 원천 데이터 및 표준화 결과 저장
- 대표 테이블
  - `fact_financial_statement`: 원천 재무 레코드 (corp_code/bsns_year/fs_div/sj_div/account_nm/amount 등)
  - `dim_account_mapping`: 계정 표준화 규칙 테이블 (account_std, match_type, pattern)
  - `dim_company`: 기업 기본정보 + `induty_code` (업종코드)

### 2.2 DuckDB (분석 저장소: data/analytics.duckdb)
- 분석/집계/점수화/리포트 생성에 사용
- 대표 테이블
  - `mart_financial_base`: DuckDB 분석의 단일 원천 테이블
  - `mart_buffett_cash_annual`: 업종 기반 capex_total + owner_earnings + fcf 생성
  - `mart_buffett_earning_power_10y`: 5~10년 장기 집계/점수
  - `mart_score_combined_yearly`: 연도별 종합 점수
  - `mart_score_combined_annual`: 최신 연도 단년도 점수 (Top20 선정 기준)

---

## 3. 전체 작업 Flow

### 3.1 설계했던 Flow(계획)
1) OpenDART 재무 데이터 수집 → SQLite 저장  
2) 계정 표준화(account_std) → 분석 가능한 최소 계정 세트 확보  
3) DuckDB Mart 생성  
4) Owner Earnings/FCF 계산  
5) 점수화(단년도 + 장기)  
6) 리포트(HTML, 그래프 포함) 자동 생성  
7) macOS 자동화(pmset + launchd + caffeinate)

### 3.2 실제 구현 Flow(최종 운영 Flow)
(실제 운영 시 아래 순서를 그대로 실행한다)

```bash
python scripts/08_0_backfill_induty_code.py
python scripts/08_1_append_investment_rules_universal.py
python scripts/08_1_account_standardize_all.py
python scripts/08_2_build_duckdb_mart.py
python scripts/08_3_rebuild_cash_mart_industry_auto_universal.py
python scripts/08_4_build_buffett_earning_power_10y.py
python scripts/09_6_build_yearly_scores.py
python scripts/10_3_batch_top20_html_reports.py

4. Script Catalog (각 파일의 용도/입력/출력)

아래는 “최종본” 기준으로 문서화한 것이다.

4.1 scripts/08_0_backfill_induty_code.py

목적: SQLite dim_company.induty_code 백필
입력:

dim_company, fact_financial_statement
OpenDART company.json API (induty_code 포함) [codestudy.net]


출력:

dim_company.induty_code 업데이트


운영 정책:

status=000 → update
status=013 → skip
status=020 → 즉시 종료(Exit non-zero) → 파이프라인 중단(다음날 재시도)
기타 status → 즉시 오류 종료



4.2 scripts/08_1_append_investment_rules_universal.py

목적: 업종 범용 “투자 후보 계정”을 표준계정(INV_*)로 매핑하기 위한 룰을 dim_account_mapping에 추가
입력: SQLite dim_account_mapping
출력: 투자/현금흐름 표준계정 룰 추가(중복 방지 INSERT)
비고: 실제 CAPEX 포함 여부는 이후 08_3에서 업종별로 자동 선택

4.3 scripts/08_1_account_standardize_all.py

목적: fact_financial_statement.account_nm → account_std 채우기
입력:

SQLite fact_financial_statement, dim_account_mapping


출력:

SQLite fact_financial_statement.account_std 업데이트(Null만 채움)



4.4 scripts/08_2_build_duckdb_mart.py

목적: DuckDB 분석의 단일 원천 테이블 mart_financial_base 생성
입력: SQLite fact_financial_statement
출력: DuckDB mart_financial_base

4.5 scripts/08_3_rebuild_cash_mart_industry_auto_universal.py

목적: 업종(induty_code)별로 CAPEX 구성 항목을 데이터 기반으로 자동 선택하여 capex_total 생성
입력:

DuckDB mart_financial_base
SQLite dim_company.induty_code


출력:

DuckDB mart_buffett_cash_annual
DuckDB dim_industry_capex_policy (업종별 항목 포함 정책)


핵심:

업종별로 항목별 coverage + median intensity(|amount|/revenue) 계산 후
기준을 넘는 항목만 CAPEX에 포함
capex_total은 Owner Earnings/FCF 차감용 “운영 투자”
invest_total은 확장 투자(리포트 참고용)



4.6 scripts/08_4_build_buffett_earning_power_10y.py

목적: 기업별 5~10년 장기 Earning Power 집계/점수
입력:

DuckDB mart_buffett_cash_annual
DuckDB mart_metrics_annual


출력:

DuckDB mart_buffett_earning_power_10y


원칙:

파생 비율은 컬럼 참조가 아니라 SELECT 내부 계산식으로 생성



4.7 scripts/09_6_build_yearly_scores.py

목적: 연도별 점수 테이블 생성
입력:

DuckDB mart_metrics_annual, mart_buffett_cash_annual, mart_buffett_earning_power_10y


출력:

DuckDB mart_score_combined_yearly
DuckDB mart_score_combined_annual (최신연도 only, year 컬럼 사용)



4.8 scripts/10_3_batch_top20_html_reports.py

목적: Top20 기업에 대해 HTML 리포트 생성(표 + 그래프 포함)
입력:

DuckDB: yearly/annual/earning_power/cash tables
SQLite: dim_company (corp_name)


출력:

output/company_reports_top20/*.html


포함 그래프:

점수 추이(quality/buffett/combined)
핵심 비율(ROE/OPM/FCF margin)
Owner Earnings vs CAPEX(막대)




5. macOS 자동화: pmset + launchd + caffeinate + pipeline
5.1 왜 launchd만으로는 “wake”가 안 되는가?
launchd(StartCalendarInterval)은 스케줄된 시각에 시스템이 잠들어 있으면,
다음에 컴퓨터가 깨어났을 때 1회 실행된다(= 놓치지 않음). 
하지만 스스로 시스템을 깨우는 기능은 없다. [alvinalexander.com], [forbes.com]
→ 따라서 “재무 데이터 수집”과 동일하게,
pmset으로 깨우고(=wake) → launchd로 실행하는 구조를 사용한다.
5.2 caffeinate 역할
caffeinate는 작업 중 시스템이 잠자기에 들어가지 않도록 유지한다.
터미널에서 caffeinate 및 옵션은 man caffeinate로 확인할 수 있으며, 일정 시간 동안 sleep을 방지할 수 있다. [news.macgasm.net]
5.3 pipeline 실행 스크립트(run_pipeline.zsh)

모든 파이썬 스크립트를 순차 실행
set -e + set -o pipefail을 사용해 앞 단계 실패 시 즉시 중단
(중요) tee 사용 시 파이프 실패가 무시되지 않도록 pipefail 필수


6. Changelog (주요 변경 내역)
6.1 계정 표준화(08_1) 개선

SQL 직접 실행 대신 Python 단일 스크립트로 표준화 수행
dim_account_mapping 기반으로 Null 값만 채우는 방식으로 반복 실행 안정성 확보

6.2 DuckDB 예약어 충돌 해결

CTE 이름으로 pivot 사용 시 DuckDB 파서 오류 발생 → 예약어 회피(CTE 이름 변경)

6.3 CAPEX 0 문제 해결(개념 오류 수정)

CAPEX가 0으로 보이던 원인: “취득 + 처분”이 같이 들어가 상쇄되거나, 업종별 계정 표현 다양성으로 누락
해결:

투자 후보 계정을 표준계정(INV_*)로 폭넓게 매핑
업종별 데이터 기반 자동 선택으로 capex_total 생성



6.4 OpenDART API 제한(020) 처리 정책 정착

013: skip
020: 파이프라인 중단을 위해 exit non-zero
run_pipeline.zsh는 pipefail 적용으로 실패 전파


7. Error Playbook (대표 에러 & 해결)
7.1 OpenDART 020 (요청 제한 초과)

증상: backfill 중 status=020
정책: 즉시 종료(exit non-zero) → 다음날 재시도
이유: 더 호출해도 손해이며 파이프라인 계속 실행하면 데이터 일관성이 깨짐

7.2 set -e인데도 다음 스크립트가 실행됨

원인: python ... | tee ... 파이프에서 exit code가 tee 기준으로 잡힘
해결: set -o pipefail 추가

7.3 CAPEX가 모든 기업에서 0으로 표시됨

원인: CAPEX 정의가 너무 좁거나(취득만/계정 누락), 업종 표현 다양성 누락
해결: INV_* 후보 매핑 확장 + 업종별 자동 선택(coverage/intensity)

7.4 launchd가 “깨우지 못함”

설명: StartCalendarInterval은 sleep 중이면 깨어난 후 실행(놓치지 않음) [alvinalexander.com], [forbes.com]
해결: pmset wake schedule 사용(재무데이터 수집과 동일 패턴)


8. 운영 팁(권장)

backfill(08_0)은 API 제한이 있으므로 “매일 새벽” 배치로 운영
08_0이 020로 종료되면 파이프라인 중단 → 다음날 재시도
업종/투자 매핑 룰은 누적 관리(중복 insert 방지로 반복 실행 안전)
HTML 리포트는 output 폴더에 날짜별 로그/결과를 남기고 VS Code Live Preview 또는 브라우저로 확인


9. 빠른 시작(Quick Start)
Shell# 1) venv 활성화source venv/bin/activate# 2) 업종코드 백필 (API 제한 시 다음 날 재시도)python scripts/08_0_backfill_induty_code.py# 3) 전체 파이프라인/usr/bin/caffeinate -dims /bin/zsh ~/Project/dart_finance/run_pipeline.zshShow more lines

10. 참고 문서

OpenDART 기업개황(company.json) 응답에 업종코드(induty_code) 포함 [codestudy.net], [code.visua...studio.com]
launchd StartCalendarInterval은 sleep 중이면 깨어난 후 실행(놓치지 않음) [alvinalexander.com], [forbes.com]
caffeinate는 sleep 방지를 위한 기본 도구(시간 옵션 포함) [news.macgasm.net]
Buffett Owner Earnings 개념(1986 Berkshire letter) [berkshireh...thaway.com], [en.wikipedia.org]

4. Script Catalog (각 파일의 용도/입력/출력)

아래는 “최종본” 기준으로 문서화한 것이다.

4.1 scripts/08_0_backfill_induty_code.py

목적: SQLite dim_company.induty_code 백필
입력:

dim_company, fact_financial_statement
OpenDART company.json API (induty_code 포함) [codestudy.net]


출력:

dim_company.induty_code 업데이트


운영 정책:

status=000 → update
status=013 → skip
status=020 → 즉시 종료(Exit non-zero) → 파이프라인 중단(다음날 재시도)
기타 status → 즉시 오류 종료



4.2 scripts/08_1_append_investment_rules_universal.py

목적: 업종 범용 “투자 후보 계정”을 표준계정(INV_*)로 매핑하기 위한 룰을 dim_account_mapping에 추가
입력: SQLite dim_account_mapping
출력: 투자/현금흐름 표준계정 룰 추가(중복 방지 INSERT)
비고: 실제 CAPEX 포함 여부는 이후 08_3에서 업종별로 자동 선택

4.3 scripts/08_1_account_standardize_all.py

목적: fact_financial_statement.account_nm → account_std 채우기
입력:

SQLite fact_financial_statement, dim_account_mapping


출력:

SQLite fact_financial_statement.account_std 업데이트(Null만 채움)



4.4 scripts/08_2_build_duckdb_mart.py

목적: DuckDB 분석의 단일 원천 테이블 mart_financial_base 생성
입력: SQLite fact_financial_statement
출력: DuckDB mart_financial_base

4.5 scripts/08_3_rebuild_cash_mart_industry_auto_universal.py

목적: 업종(induty_code)별로 CAPEX 구성 항목을 데이터 기반으로 자동 선택하여 capex_total 생성
입력:

DuckDB mart_financial_base
SQLite dim_company.induty_code


출력:

DuckDB mart_buffett_cash_annual
DuckDB dim_industry_capex_policy (업종별 항목 포함 정책)


핵심:

업종별로 항목별 coverage + median intensity(|amount|/revenue) 계산 후
기준을 넘는 항목만 CAPEX에 포함
capex_total은 Owner Earnings/FCF 차감용 “운영 투자”
invest_total은 확장 투자(리포트 참고용)



4.6 scripts/08_4_build_buffett_earning_power_10y.py

목적: 기업별 5~10년 장기 Earning Power 집계/점수
입력:

DuckDB mart_buffett_cash_annual
DuckDB mart_metrics_annual


출력:

DuckDB mart_buffett_earning_power_10y


원칙:

파생 비율은 컬럼 참조가 아니라 SELECT 내부 계산식으로 생성



4.7 scripts/09_6_build_yearly_scores.py

목적: 연도별 점수 테이블 생성
입력:

DuckDB mart_metrics_annual, mart_buffett_cash_annual, mart_buffett_earning_power_10y


출력:

DuckDB mart_score_combined_yearly
DuckDB mart_score_combined_annual (최신연도 only, year 컬럼 사용)



4.8 scripts/10_3_batch_top20_html_reports.py

목적: Top20 기업에 대해 HTML 리포트 생성(표 + 그래프 포함)
입력:

DuckDB: yearly/annual/earning_power/cash tables
SQLite: dim_company (corp_name)


출력:

output/company_reports_top20/*.html


포함 그래프:

점수 추이(quality/buffett/combined)
핵심 비율(ROE/OPM/FCF margin)
Owner Earnings vs CAPEX(막대)




5. macOS 자동화: pmset + launchd + caffeinate + pipeline
5.1 왜 launchd만으로는 “wake”가 안 되는가?
launchd(StartCalendarInterval)은 스케줄된 시각에 시스템이 잠들어 있으면,
다음에 컴퓨터가 깨어났을 때 1회 실행된다(= 놓치지 않음). 
하지만 스스로 시스템을 깨우는 기능은 없다. [alvinalexander.com], [forbes.com]
→ 따라서 “재무 데이터 수집”과 동일하게,
pmset으로 깨우고(=wake) → launchd로 실행하는 구조를 사용한다.
5.2 caffeinate 역할
caffeinate는 작업 중 시스템이 잠자기에 들어가지 않도록 유지한다.
터미널에서 caffeinate 및 옵션은 man caffeinate로 확인할 수 있으며, 일정 시간 동안 sleep을 방지할 수 있다. [news.macgasm.net]
5.3 pipeline 실행 스크립트(run_pipeline.zsh)

모든 파이썬 스크립트를 순차 실행
set -e + set -o pipefail을 사용해 앞 단계 실패 시 즉시 중단
(중요) tee 사용 시 파이프 실패가 무시되지 않도록 pipefail 필수


6. Changelog (주요 변경 내역)
6.1 계정 표준화(08_1) 개선

SQL 직접 실행 대신 Python 단일 스크립트로 표준화 수행
dim_account_mapping 기반으로 Null 값만 채우는 방식으로 반복 실행 안정성 확보

6.2 DuckDB 예약어 충돌 해결

CTE 이름으로 pivot 사용 시 DuckDB 파서 오류 발생 → 예약어 회피(CTE 이름 변경)

6.3 CAPEX 0 문제 해결(개념 오류 수정)

CAPEX가 0으로 보이던 원인: “취득 + 처분”이 같이 들어가 상쇄되거나, 업종별 계정 표현 다양성으로 누락
해결:

투자 후보 계정을 표준계정(INV_*)로 폭넓게 매핑
업종별 데이터 기반 자동 선택으로 capex_total 생성



6.4 OpenDART API 제한(020) 처리 정책 정착

013: skip
020: 파이프라인 중단을 위해 exit non-zero
run_pipeline.zsh는 pipefail 적용으로 실패 전파


7. Error Playbook (대표 에러 & 해결)
7.1 OpenDART 020 (요청 제한 초과)

증상: backfill 중 status=020
정책: 즉시 종료(exit non-zero) → 다음날 재시도
이유: 더 호출해도 손해이며 파이프라인 계속 실행하면 데이터 일관성이 깨짐

7.2 set -e인데도 다음 스크립트가 실행됨

원인: python ... | tee ... 파이프에서 exit code가 tee 기준으로 잡힘
해결: set -o pipefail 추가

7.3 CAPEX가 모든 기업에서 0으로 표시됨

원인: CAPEX 정의가 너무 좁거나(취득만/계정 누락), 업종 표현 다양성 누락
해결: INV_* 후보 매핑 확장 + 업종별 자동 선택(coverage/intensity)

7.4 launchd가 “깨우지 못함”

설명: StartCalendarInterval은 sleep 중이면 깨어난 후 실행(놓치지 않음) [alvinalexander.com], [forbes.com]
해결: pmset wake schedule 사용(재무데이터 수집과 동일 패턴)


8. 운영 팁(권장)

backfill(08_0)은 API 제한이 있으므로 “매일 새벽” 배치로 운영
08_0이 020로 종료되면 파이프라인 중단 → 다음날 재시도
업종/투자 매핑 룰은 누적 관리(중복 insert 방지로 반복 실행 안전)
HTML 리포트는 output 폴더에 날짜별 로그/결과를 남기고 VS Code Live Preview 또는 브라우저로 확인


9. 빠른 시작(Quick Start)
Shell
# 1) venv 활성화
source venv/bin/activate
# 2) 업종코드 백필 (API 제한 시 다음 날 재시도)
python scripts/08_0_backfill_induty_code.py
# 3) 전체 파이프라인
/usr/bin/caffeinate -dims /bin/zsh ~/Project/dart_finance/run_pipeline.zshShow more lines

10. 참고 문서

OpenDART 기업개황(company.json) 응답에 업종코드(induty_code) 포함 [codestudy.net], [code.visua...studio.com]
launchd StartCalendarInterval은 sleep 중이면 깨어난 후 실행(놓치지 않음) [alvinalexander.com], [forbes.com]
caffeinate는 sleep 방지를 위한 기본 도구(시간 옵션 포함) [news.macgasm.net]
Buffett Owner Earnings 개념(1986 Berkshire letter) [berkshireh...thaway.com], [en.wikipedia.org]

