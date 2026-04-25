# FinSentinel

> 규칙 기반 금융 이상거래탐지(FDS) 파이프라인 · 서비스 품질 관리 · 야간배치 시뮬레이션

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![CI](https://github.com/jeong-inn/FinSentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/jeong-inn/FinSentinel/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 목차

- [개요](#개요)
- [파이프라인 구조](#파이프라인-구조)
- [주요 기능](#주요-기능)
- [시작하기](#시작하기)
- [디렉토리 구조](#디렉토리-구조)
- [FDS 탐지 규칙](#fds-탐지-규칙)
- [시나리오 설계](#시나리오-설계)
- [야간배치](#야간배치)
- [데이터 품질 관리](#데이터-품질-관리)
- [대시보드](#대시보드)
- [테스트](#테스트)
- [기술 스택](#기술-스택)

---

## 개요

FinSentinel은 한국 시중은행의 **이상거래탐지시스템(FDS, Fraud Detection System)** 운영 프로세스를 Python으로 구현한 파이프라인임.

금융보안원 FDS 운영 가이드라인 및 특정금융거래정보법(KoFIU)의 STR·CTR 보고 체계를 반영하여, 합성 거래 데이터 생성부터 탐지·판정·야간배치·규제 리포팅까지 **11단계 파이프라인**으로 구성됨.

```
10,000건 합성 거래  →  9개 FDS 규칙 탐지  →  상태 머신  →  최종 판정
→  SPC/SQM 품질 분석  →  DQM 4차원 검증  →  야간배치  →  PostgreSQL + 대시보드
```

---

## 파이프라인 구조

```
Stage  모듈                      설명
─────────────────────────────────────────────────────────────────
 1     generate_logs.py          합성 거래 로그 생성 (seed=42, 재현 가능)
 2     preprocess.py             Rolling features 추가 (window=20)
 3     anomaly_detector.py       9개 FDS 규칙 이상 탐지 (벡터화)
 4     state_engine.py           거래 상태 머신 (NORMAL → FAIL)
 5     judge.py                  시나리오 최종 판정
 6     validator.py              Spec 대비 검증 & 릴리즈 게이트
 7     spc.py                    서비스 품질 분석 — Cpk/Ppk + WE Rules 8가지
 8     root_cause.py             이상 원인 분석
 9     dq_monitor.py             DQM 4차원 데이터 품질 검증
10     batch_processor.py        야간배치 — 일일결산/한도점검/STR후보/정합성검증
11     db_writer.py              PostgreSQL 저장 (8 tables, 9 views)
```

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **FDS 규칙 엔진** | 9개 규칙 기반 이상 탐지. numpy 벡터화로 10,000건 기준 ~50x 성능 |
| **금융 규제 대응** | STR(의심거래보고) · CTR(고액거래보고) · KoFIU 보고 체계 |
| **상태 머신** | NORMAL → WARNING → CRITICAL → RECOVERY → FAIL 5단계 전이 |
| **SPC/SQM** | Cpk/Ppk 서비스 수준 능력 지수 + Western Electric 8 Rules |
| **야간배치** | 일일결산 · 한도점검 · STR 후보 추출 · 원장 정합성 검증 |
| **DQM** | 완전성 · 정합성 · 적시성 · 정확성 4차원 가중 평균 품질 등급 |
| **대시보드** | Streamlit 6-tab 운영 모니터링 화면 |
| **CI/CD** | GitHub Actions — lint(ruff) → test(pytest) → docker build |

---

## 시작하기

### 요구사항

- Python 3.10+
- PostgreSQL 16 (선택 — 없어도 파이프라인 실행 가능)
- Docker & Docker Compose (선택)

### 로컬 실행

```bash
# 1. 저장소 클론
git clone https://github.com/jeong-inn/FinSentinel.git
cd FinSentinel

# 2. 가상환경 & 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 거래 로그 생성
python3 src/generate_logs.py

# 4. 파이프라인 실행
python3 src/main.py

# 5. 대시보드 실행
streamlit run app.py
```

### Docker로 실행

```bash
# PostgreSQL + 파이프라인 + 대시보드 일괄 실행
docker compose up --build

# 대시보드 접속
open http://localhost:8501
```

---

## 디렉토리 구조

```
FinSentinel/
├── src/
│   ├── main.py                # 파이프라인 오케스트레이터 (11-Stage)
│   ├── generate_logs.py       # 합성 거래 로그 생성
│   ├── preprocess.py          # 전처리 (Rolling features)
│   ├── anomaly_detector.py    # FDS 규칙 기반 이상 탐지
│   ├── state_engine.py        # 거래 상태 머신
│   ├── judge.py               # 시나리오 최종 판정
│   ├── validator.py           # Spec 검증 & 릴리즈 게이트
│   ├── policy_engine.py       # 금융 규제 대응 정책
│   ├── spc.py                 # 서비스 품질 관리 (Cpk/Ppk/WE Rules)
│   ├── root_cause.py          # 이상 원인 분석
│   ├── batch_processor.py     # 야간배치 처리
│   ├── dq_monitor.py          # DQM 데이터 품질 검증
│   ├── operator_report.py     # 운영자 리포트 생성
│   ├── llm_reporter.py        # LLM 기반 리포트 (GPT-4o, 선택)
│   └── db_writer.py           # PostgreSQL 저장
├── tests/
│   ├── test_pipeline.py       # 통합 테스트 (27개)
│   └── test_spc.py            # SPC 단위 테스트 (17개)
├── db/
│   └── init.sql               # PostgreSQL DDL (8 tables, 9 views)
├── data/
│   ├── raw/                   # 생성된 거래 로그
│   ├── processed/             # 파이프라인 산출물 (재생성 가능)
│   └── scenarios/
│       └── scenario_specs.json  # 시나리오 검증 스펙
├── app.py                     # Streamlit 대시보드
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/ci.yml   # CI 파이프라인
└── requirements.txt
```

---

## FDS 탐지 규칙

총 **9개 규칙**을 numpy 벡터 연산으로 적용함. iterrows 대신 boolean mask를 사용하여 10,000건 기준 약 50배 성능을 확보함.

| ID | 규칙명 | 조건 | 비고 |
|----|--------|------|------|
| R1 | `amount_high` | `tx_amount ≥ 65만원` | CTR 보고 기준 근접 |
| R2 | `amount_spike` | `\|금액 차분\| ≥ 8` | Rolling mean 대비 급변 |
| R3 | `processing_time_high` | `processing_time_ms ≥ 135` | SLA 위반 |
| R4 | `processing_time_jump` | `처리시간 차분 ≥ 15ms` | 급격한 처리 지연 |
| R5 | `tx_error_detected` | `error_code ≠ 0` | 거래 오류 발생 |
| R6 | `response_dropout` | `response_time_ms ≤ 1` | FDS 응답 장애 |
| R7 | `fraud_event` | `fraud_flag = 1` | 이상거래 플래그 |
| R8 | `fds_night_high_amount` | 심야(00~05시) + `tx_amount ≥ 60` | FDS 강화 규칙 |
| R9 | `fds_high_risk_transfer` | CDD 등급 ≥ 4 + TRANSFER + `≥ 58만원` | FDS 강화 규칙 |

### 대응 액션 체계

탐지 결과에 따라 금융보안원·KoFIU 가이드라인 기반 대응 액션이 결정됨.

```
NO_ACTION → ENHANCED_MONITORING → CTR_REVIEW → STR_REVIEW
         → STR_FILING → TRANSACTION_BLOCK → EMERGENCY_HALT
```

| 액션 | 설명 |
|------|------|
| `ENHANCED_MONITORING` | 강화모니터링 — 거래 추이 지속 관찰 |
| `CTR_REVIEW` | 고액거래보고 검토 (1일 1천만원 이상) |
| `STR_REVIEW` | 의심거래보고 분석 |
| `STR_FILING` | KoFIU 의심거래보고 제출 |
| `TRANSACTION_BLOCK` | 계좌·채널 거래 즉시 차단 |
| `EMERGENCY_HALT` | 시스템 전면 중단 및 보안팀 에스컬레이션 |

---

## 시나리오 설계

10개 시나리오로 FDS 파이프라인의 탐지 능력을 검증함. 각 시나리오는 1,000건의 거래로 구성됨(1 Branch × 5 Accounts × 8 Channels × 25 tx).

| 시나리오 | 패턴 | 최종 판정 | 권고 액션 |
|----------|------|-----------|-----------|
| S1 | 정상 거래 (baseline) | PASS | NO_ACTION |
| S2 | 금액 스파이크 후 회복 | PASS_WITH_WARNING | ENHANCED_MONITORING |
| S3 | 지속 상승 (자금세탁 의심) | FAIL | STR_FILING |
| S4 | 처리시간 점진 증가 | PASS_WITH_WARNING | ENHANCED_MONITORING |
| S5 | 반복 에러 (네트워크) | PASS_WITH_WARNING | NO_ACTION |
| S6 | FDS 응답 손실 (채널 장애) | FAIL | TRANSACTION_BLOCK |
| S7 | 변동성 burst 후 회복 | PASS_WITH_WARNING | ENHANCED_MONITORING |
| S8 | 복합 이상 (다중 규칙 위반) | FAIL | EMERGENCY_HALT |
| S9 | 재검증 통과 | PASS_WITH_WARNING | CTR_REVIEW |
| S10 | 회복 실패 | FAIL | EMERGENCY_HALT |

- 전체 10,000건 거래 / 이상 탐지율 약 29.8%
- 시나리오 검증 매치율 7/10 — S8·S9·S10은 임계값 민감도로 인한 자연 오차임

---

## 야간배치

실제 시중은행의 야간배치(Nightly Batch) 프로세스를 4단계로 구현함. 은행에서는 Spring Batch + 계정계 원장을 사용하지만, 여기서는 pandas로 핵심 로직을 재현함.

```
일일결산 → 한도점검 → STR 후보 추출 → 정합성 검증
```

| 배치 | 설명 |
|------|------|
| **일일결산** | 계좌별 입금/출금/이체/결제 집계 및 순거래금액 산출 |
| **한도점검** | 1일 거래한도(5천만원) 초과 및 CTR 보고 기준(1천만원) 식별 |
| **STR 후보** | 이상 탐지 3건 이상 또는 FAIL 시나리오 → URGENT/HIGH/MEDIUM/LOW 우선순위 |
| **정합성검증** | 원거래 로그 ↔ 결산 데이터 건수·금액 교차 검증 |

---

## 데이터 품질 관리

BIS Basel II/III 및 금융감독원 데이터 품질 가이드라인 기반의 **4차원 DQM**을 수행함.

| 차원 | 가중치 | 검증 내용 |
|------|--------|-----------|
| 완전성 (Completeness) | 30% | 필수 10개 컬럼 결측치 |
| 정합성 (Consistency) | 25% | 음수 금액·거래유형·위험등급 논리 일관성 |
| 적시성 (Timeliness) | 20% | 처리시간 200ms 초과·FDS 응답 50ms 초과 |
| 정확성 (Accuracy) | 25% | 값 범위·포맷 유효성 (5개 컬럼) |

**등급 기준**: A(≥95%) · B(≥85%) · C(≥70%) · D(<70%)

---

## 대시보드

```bash
streamlit run app.py
# http://localhost:8501
```

| 탭 | 내용 |
|----|------|
| 타임라인 | 거래금액·FDS응답·처리시간 시계열, 상태별 색상 구분 |
| 서비스 품질 (SPC) | X-bar 관리도, Cpk/Ppk, WE Rules 8가지 위반 현황 |
| 계좌 분석 | 계좌별 파라미터 분포, Channel × Account 히트맵 |
| 판정 요약 | 전 시나리오 판정·검증·릴리즈 게이트 테이블 |
| 야간배치 | 일일결산, STR 후보 목록, 정합성 검증 결과 |
| 데이터 품질 | DQM 4차원 등급 카드, 검증 기준 테이블 |

---

## 테스트

```bash
# 전체 테스트 실행
python3 -m pytest tests/ -v --tb=short

# 커버리지 포함
python3 -m pytest tests/ --cov=src --cov-report=term-missing
```

총 **44개 테스트** (통합 27 + SPC 단위 17)

| 영역 | 주요 검증 |
|------|-----------|
| 데이터 생성 | 시나리오 수, row 수, 필수 컬럼, 거래 유형, CDD 등급 분포 |
| 이상 탐지 | 시나리오별 규칙 탐지 여부 (dropout, fraud_event, amount_high) |
| 상태 분류 | 유효 상태값, FAIL 전이 조건 |
| 최종 판정 | PASS/PASS_WITH_WARNING/FAIL, 권고 액션 |
| SPC/SQM | S1 Cpk ≥ 1.33, S3 Cpk < 1.0 |
| 야간배치 | 결산 50건(10×5), STR 후보 포함 여부, 정합성 count_match |
| DQM | 완전성 100%, 종합 등급 A/B |

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.10 |
| 데이터 처리 | pandas · numpy (벡터화 이상 탐지) |
| 시각화 | Streamlit · Plotly |
| 데이터베이스 | PostgreSQL 16 · psycopg2 |
| 컨테이너 | Docker · Docker Compose |
| CI/CD | GitHub Actions (lint → test → docker) |
| 코드 품질 | ruff · pytest |
| LLM 연동 | OpenAI GPT-4o (선택, `OPENAI_API_KEY` 설정 시) |

---

## 환경변수

```bash
# .env 파일 생성
DB_HOST=localhost
DB_PORT=5432
DB_NAME=finsentinel
DB_USER=postgres
DB_PASSWORD=your_password

OPENAI_API_KEY=sk-...   # 선택 — LLM 리포트 사용 시
```

---

## 라이선스

[MIT License](LICENSE)
