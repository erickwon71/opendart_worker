# DART Finance Analytics Pipeline

OpenDART 재무공시 데이터를 기반으로 기업의 재무체력을 분석하고,  
Warren Buffett의 Owner Earnings 관점과 장기 Earning Power를 중심으로  
**업종별 자동 해석이 가능한 투자 분석 파이프라인**을 구축하는 프로젝트입니다.

---

## 1. Project Overview

### 1.1 목적
본 프로젝트의 목표는 다음 질문에 정량적으로 답하는 것입니다.

- 이 기업은 **현금을 얼마나 안정적으로 벌어들이는가?**
- 그 현금은 **유지(maintenance)**를 위해 얼마를 다시 써야 하는가?
- 업종에 따라 달라지는 CAPEX를 **사람의 개입 없이** 자동으로 해석할 수 있는가?
- 단기 실적이 아니라 **5~10년 장기 체력(Earning Power)**은 어떤가?

이를 위해 단순 ETL이 아닌,  
**“계정 표기 불확실성을 흡수하는 재무 해석 파이프라인”**으로 설계되었습니다.

---

## 2. Data Sources

### 2.1 OpenDART
- 재무상태표 / 손익계산서 / 현금흐름표
- 사업보고서(reprt_code = 11011) 기준
- 기업개황(company.json)으로부터 업종코드(induty_code) 사용

### 2.2 업종코드(induty_code)의 역할
- 업종별로 CAPEX 정의가 다르다는 문제를 해결하기 위한 핵심 메타 정보
- CAPEX 자동 선택 로직(08_3)의 기준 축(axis)

---

## 3. High-Level Architecture

### 3.1 Storage Layer 분리
| Layer | 역할 |
|------|------|
| SQLite (`opendart.sqlite`) | 원천 데이터 저장소 (정규화 / 표준화) |
| DuckDB (`analytics.duckdb`) | 분석/집계/Mart 전용 |

> SQLite는 **기록용**, DuckDB는 **계산용**

---

### 3.2 핵심 설계 원칙 (중요)

#### ✅ 역할 분리 원칙
- **account_std**
  - 투자/현금/CapEx 분류용
  - Owner Earnings, FCF 계산에 사용
- **account_nm**
  - 재무제표 핵심 지표(매출/영업이익/자본총계 등)
  - Metrics(ROE, OPM, 부채비율) 계산에 사용

> 이유:  
> 계정 표준화(account_std)는 표현 차이를 100% 흡수할 수 없지만,  
> 핵심 지표는 실존 계정명을 직접 탐지하는 것이 훨씬 안정적이기 때문

---

## 4. End-to-End Pipeline Flow

```text
08_0 Backfill Industry Code
08_1d Strengthen Account Mapping (Data-driven, optional)
08_1 Account Standardization (SQLite)
08_2 Build DuckDB Marts (Base + Metrics + Growth)
08_3 Industry-aware Cash & CAPEX Mart
08_4 Buffett Earning Power (5~10Y)
09_6 Yearly Scoring
10_3 Top20 HTML Report

5. Script Breakdown (Detailed)
5.1 08_0_backfill_induty_code.py

기업개황 API로 업종코드 백필
실제 재무 데이터가 존재하는 기업만 Universe로 사용
API status 정책

000: 정상
013: skip
020: 즉시 종료 (non-zero exit)




5.2 08_1d_strengthen_metric_mappings_from_data.py

DuckDB의 mart_financial_base에서 실제 많이 쓰이는 account_nm 자동 탐색
매출 / 영업이익 / 자산 / 자본 등 핵심 계정
LIKE 패턴으로 dim_account_mapping에 영구 보강
이후 신규 기업/연도 추가 시에도 안정성 확보


5.3 08_1_account_standardize_all.py

dim_account_mapping 규칙을 이용해 account_std 채움
기존 값은 덮어쓰지 않음 (멱등성 보장)
수백만 행 업데이트 → 수 분 소요 정상


5.4 08_2_build_duckdb_mart.py

DuckDB 분석용 Mart 구축
생성 테이블

mart_financial_base
mart_metrics_annual
mart_growth_annual


핵심 변경:

Metrics는 account_nm 기반 LIKE 매칭 사용




5.5 08_3_rebuild_cash_mart_industry_auto_universal.py

업종별로 “운영 CAPEX”를 자동 선택
기준:

Coverage (≥ 20%)
Intensity (median |CAPEX| / revenue ≥ 0.5%)


산출:

capex_total (Owner Earnings 차감용)
free_cash_flow
owner_earnings




5.6 08_4_build_buffett_earning_power_10y.py

최근 5~10년 데이터 사용
평균/변동성/지속성 기반 Earning Power Score
단기 왜곡 제거 목적


5.7 09_6_build_yearly_scores.py

연도별 상대 평가
Quality + Buffett + Combined Score
mart_metrics_annual + mart_buffett_cash_annual 결합


5.8 10_3_batch_top20_html_reports.py

Top 20 기업 HTML 리포트 자동 생성
포함 내용

점수 추이
핵심 재무 지표
Owner Earnings vs CAPEX


결과물: /output/company_reports_top20/*.html


6. Automation & Operations
6.1 macOS 자동화 구조

pmset: 시스템 wake
launchd: 스케줄 실행
caffeinate: 실행 중 sleep 방지
run_pipeline.zsh

set -e
set -o pipefail




7. Troubleshooting Guide (요약)

























증상원인해결09_6 결과 0 rowsrevenue/roe NULL08_2 metrics 부분 account_nm 기반 확인owner_earnings NULLnet_income 미집계08_3 동의어 포함 여부 확인pipeline 중간 진행pipefail 미적용run_pipeline.zsh 확인

8. Change Log

👉 본 섹션은 별도 Change Log 섹션에 상세 기록
(2026-05 기준 파이프라인 설계 확정 및 안정화 완료)

✅ 2026-05 — 파이프라인 안정화 & 핵심 설계 확정
1. 업종코드(induty_code) 백필 파이프라인 확정

OpenDART company.json API를 이용해 dim_company.induty_code를 백필하는 단계(08_0_backfill_induty_code.py) 확정
재무 데이터가 실제로 존재하는 기업만 업종 분석 대상 Universe로 삼도록 기준 명확화
OpenDART API 상태 코드 정책 확정

000: 정상 처리
013: 데이터 없음 → skip
020: API limit 초과 → 즉시 exit(non-zero) 하여 전체 파이프라인 중단 (다음날 재시도)




2. SQLite → DuckDB Mart 경계 재설계 (08_2)

SQLite는 원천 저장소, DuckDB는 분석/집계 전용 저장소로 역할을 명확히 분리
DuckDB에서 SQLite sqlite_master 메타테이블을 직접 접근하는 방식 제거

DuckDB 공식 권장 방식(ATTACH … (TYPE SQLITE) + CREATE OR REPLACE)으로 전환


mart_financial_base를 모든 분석 단계의 **단일 원천 테이블(Single Source of Truth)**로 확정


3. CAPEX & Owner Earnings 계산 로직 정상화 (08_3)

문제 원인:

owner_earnings가 전부 NULL로 나오는 현상 발생
원인 분석 결과, net_income, revenue, cfo 등이 표준계정(account_std) 이름 불일치로 집계되지 않음


해결:

tmp_cash_wide 생성 시 한국어/영문 표준계정 동의어를 함께 집계

예:

Net Income: NET_INCOME, 당기순이익
Revenue: REVENUE, 매출액
CFO: CFO, 영업활동현금흐름
Depreciation: DEPRECIATION, 감가상각비, 감가상각비및무형자산상각비






결과:

mart_buffett_cash_annual.owner_earnings 정상 생성
NOT NULL rows: 13,001 / 13,077




4. 핵심 결정: Metrics(ROE/OPM)는 account_nm 기반으로 계산

문제 상황:

mart_metrics_annual.revenue / roe / opm이 전부 NULL
원인:

account_std는 “분해/투자 항목 분류”에는 적합
매출/영업이익/자본총계 같은 재무제표 핵심 계정은 회사별 표기 차이가 매우 큼
account_std를 덮어쓰지 않는 정책으로 인해 일부 핵심 계정은 표준화에서 누락




설계 변경(중요):

Metrics 계산은 account_std가 아닌 account_nm 기반 LIKE 매칭을 사용
적용 대상:

Revenue
Operating Income
Net Income
Assets / Liabilities / Equity




설계 원칙 확정:

✅ account_std → CAPEX / 투자분류 / Owner Earnings용
✅ account_nm → Metrics(ROE/OPM/재무비율)용


이 결정으로:

mart_metrics_annual.revenue IS NOT NULL 문제 완전 해결
09_6_build_yearly_scores.py에서 연도별 점수 정상 생성




5. 계정 표준화 규칙의 “영구 보강 자동화” 도입 (08_1d)

문제:

회사마다 계정명 표현이 달라 수작업 매핑은 유지보수 비용이 큼


해결:

mart_financial_base에서 실제 빈도 높은 account_nm을 자동 분석
매출/영업이익/자산/부채/자본/순이익/현금흐름 계정을 대상으로
LIKE 패턴을 자동 생성하여 dim_account_mapping에 영구 추가


스크립트:

08_1d_strengthen_metric_mappings_from_data.py


효과:

이후 신규 기업/연도가 추가되어도,
08_2만 실행하면 metrics가 안정적으로 생성되는 구조 완성




6. 파이프라인 실행 순서 안정화

최종 권장 순서 확정:

Shell08_0_backfill_induty_code.py08_1d_strengthen_metric_mappings_from_data.py   # (필요 시)08_1_account_standardize_all.py08_2_build_duckdb_mart.py08_3_rebuild_cash_mart_industry_auto_universal.py08_4_build_buffett_earning_power_10y.py09_6_build_yearly_scores.py10_3_batch_top20_html_reports.pyShow more lines

09_6이 0 rows로 나올 경우:

항상 mart_metrics_annual.revenue IS NOT NULL 여부부터 확인하도록 운영 가이드 명시




7. 운영 자동화 관련 정책 정리

macOS 자동화 구성:

pmset: 시스템 wake
launchd: 시간 기반 실행
caffeinate: 파이프라인 실행 중 sleep 방지


run_pipeline.zsh에 적용된 정책:

set -e, set -o pipefail로 단계 실패 시 즉시 중단
API limit(020) 발생 시 다음 단계 실행 방지




✅ 요약 (이 Change Log의 핵심 메시지)

이 프로젝트는 단순 ETL이 아니라,
**“계정 표기 불확실성을 흡수하는 재무 데이터 해석 파이프라인”**로 설계가 진화했다.
가장 중요한 설계 결정은:

Metrics는 account_nm 기반
Cash/Investment는 account_std 기반


이 Change Log는 그 결정의 맥락을 보존하기 위한 문서이다.



9. Design Philosophy (중요)

표준화는 완벽할 수 없다
데이터는 “깨끗하게 만들기”보다
깨질 수 있는 전제를 흡수하는 구조가 중요
이 프로젝트는

회계 숫자 나열이 아니라
“현금 창출 구조” 를 해석하는 도구




10. Disclaimer

본 프로젝트는 투자 판단의 참고 자료이며,
최종 투자 결정 및 책임은 사용자에게 있습니다.