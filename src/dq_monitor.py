"""
dq_monitor.py — 데이터 품질 관리(DQM) 모듈

금융 데이터 품질 관리 4차원 검증을 수행한다.
BIS(Basel II/III) 및 금융감독원 데이터 품질 가이드라인을 참고.

4차원 품질 검증 체계:
  1. 완전성 (Completeness)  — 필수 컬럼 결측치 검사
  2. 정합성 (Consistency)   — 컬럼 간 논리적 일관성 검증
  3. 적시성 (Timeliness)    — 거래 처리 지연 여부 검사
  4. 정확성 (Accuracy)      — 값 범위/포맷 유효성 검증

등급 체계:
  A (≥ 95%): 우수 — 정상 운영
  B (≥ 85%): 양호 — 모니터링 필요
  C (≥ 70%): 미흡 — 개선 조치 필요
  D (< 70%): 부적합 — 즉시 시정 필요

DQM은 규제 보고(KoFIU, 금감원) 데이터의 신뢰성을 담보하는 필수 프로세스.
"""

import pandas as pd
import numpy as np


# ================================================================
# DQM 설정
# ================================================================

# 필수 컬럼 목록 (결측 불허)
REQUIRED_COLUMNS = [
    "timestamp", "branch_id", "account_id", "channel_id",
    "scenario_id", "tx_amount", "response_time_ms",
    "processing_time_ms", "error_code", "fraud_flag",
]

# 값 범위 규격 (정확성 검증용)
VALUE_SPECS = {
    "tx_amount": {"min": 0, "max": 10000},            # 0 ~ 1억원
    "response_time_ms": {"min": 0, "max": 5000},       # 0 ~ 5초
    "processing_time_ms": {"min": 0, "max": 10000},    # 0 ~ 10초
    "error_code": {"min": 0, "max": 999},               # 3자리 코드
    "fraud_flag": {"allowed": [0, 1]},                   # 이진값
}

# 적시성 기준
TIMELINESS_THRESHOLD_MS = 200  # 처리시간 200ms 초과 시 지연 판정


def check_completeness(df):
    """
    완전성 검사: 필수 컬럼의 결측치(NULL/NaN) 비율을 측정한다.

    BIS 데이터 품질 기준: 필수 항목 결측률 0% 목표.

    Returns:
        dict: {
            "score": float (0~100),
            "total_cells": int,
            "missing_cells": int,
            "details": list[dict]  — 컬럼별 결측 현황
        }
    """
    details = []
    total_cells = 0
    missing_cells = 0

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            n = len(df)
            details.append({
                "column": col,
                "total": n,
                "missing": n,
                "missing_rate": 1.0,
                "status": "COLUMN_MISSING",
            })
            total_cells += n
            missing_cells += n
        else:
            n = len(df)
            n_missing = int(df[col].isna().sum())
            rate = n_missing / n if n > 0 else 0

            details.append({
                "column": col,
                "total": n,
                "missing": n_missing,
                "missing_rate": round(rate, 6),
                "status": "PASS" if n_missing == 0 else "FAIL",
            })
            total_cells += n
            missing_cells += n_missing

    score = ((total_cells - missing_cells) / total_cells * 100) if total_cells > 0 else 0

    return {
        "dimension": "completeness",
        "score": round(score, 2),
        "total_cells": total_cells,
        "missing_cells": missing_cells,
        "details": details,
    }


def check_consistency(df):
    """
    정합성 검사: 컬럼 간 논리적 관계가 성립하는지 검증한다.

    검증 규칙:
    C1. error_code > 0 이면 fraud_flag 또는 anomaly가 동반될 수 있음 (경고만)
    C2. response_time_ms = 0 이면 dropout으로 분류되어야 함
    C3. tx_amount > 0 (음수 거래금액 불가)
    C4. tx_type이 있으면 유효한 값이어야 함

    Returns:
        dict: 정합성 점수 및 위반 상세
    """
    n = len(df)
    violations = []

    # C1: 음수 거래금액
    neg_amount = (df["tx_amount"] < 0).sum()
    if neg_amount > 0:
        violations.append({
            "rule": "C1_no_negative_amount",
            "violation_count": int(neg_amount),
            "description": "음수 거래금액 존재",
        })

    # C2: response_time_ms dropout 일관성
    if "anomaly_reason" in df.columns:
        dropout_mask = df["response_time_ms"] <= 1
        has_dropout_reason = df["anomaly_reason"].str.contains("response_dropout", na=False)
        inconsistent = dropout_mask & ~has_dropout_reason & (df.get("anomaly_flag", pd.Series([0]*n)) == 1)
        inconsistent_count = int(inconsistent.sum())
        if inconsistent_count > 0:
            violations.append({
                "rule": "C2_dropout_consistency",
                "violation_count": inconsistent_count,
                "description": "response_time ≤ 1ms이나 dropout으로 분류되지 않음",
            })

    # C3: tx_type 유효성
    if "tx_type" in df.columns:
        valid_types = {"DEPOSIT", "WITHDRAWAL", "TRANSFER", "PAYMENT"}
        invalid_type = ~df["tx_type"].isin(valid_types)
        invalid_count = int(invalid_type.sum())
        if invalid_count > 0:
            violations.append({
                "rule": "C3_valid_tx_type",
                "violation_count": invalid_count,
                "description": "유효하지 않은 거래 유형 존재",
            })

    # C4: customer_risk_level 범위
    if "customer_risk_level" in df.columns:
        invalid_risk = ~df["customer_risk_level"].isin([1, 2, 3, 4, 5])
        invalid_count = int(invalid_risk.sum())
        if invalid_count > 0:
            violations.append({
                "rule": "C4_valid_risk_level",
                "violation_count": invalid_count,
                "description": "유효하지 않은 고객 위험등급",
            })

    total_checks = n * 4  # 4개 규칙 × row 수
    total_violations = sum(v["violation_count"] for v in violations)
    score = ((total_checks - total_violations) / total_checks * 100) if total_checks > 0 else 100

    return {
        "dimension": "consistency",
        "score": round(score, 2),
        "total_checks": total_checks,
        "total_violations": total_violations,
        "details": violations,
    }


def check_timeliness(df):
    """
    적시성 검사: 거래 처리 지연 여부를 측정한다.

    금융보안원 권고: FDS 실시간 탐지 30ms 이내, 채널 처리 200ms 이내.

    Returns:
        dict: 적시성 점수 및 지연 건수
    """
    n = len(df)

    delayed_mask = df["processing_time_ms"] > TIMELINESS_THRESHOLD_MS
    delayed_count = int(delayed_mask.sum())

    # FDS 응답시간 기준
    fds_delayed = (df["response_time_ms"] > 50).sum()  # 50ms 초과

    details = [
        {
            "metric": "processing_time_delay",
            "threshold_ms": TIMELINESS_THRESHOLD_MS,
            "delayed_count": delayed_count,
            "delayed_rate": round(delayed_count / n, 6) if n > 0 else 0,
        },
        {
            "metric": "fds_response_delay",
            "threshold_ms": 50,
            "delayed_count": int(fds_delayed),
            "delayed_rate": round(int(fds_delayed) / n, 6) if n > 0 else 0,
        },
    ]

    on_time_count = n - delayed_count
    score = (on_time_count / n * 100) if n > 0 else 100

    return {
        "dimension": "timeliness",
        "score": round(score, 2),
        "total_transactions": n,
        "on_time_count": on_time_count,
        "delayed_count": delayed_count,
        "details": details,
    }


def check_accuracy(df):
    """
    정확성 검사: 값의 범위 및 포맷 유효성을 검증한다.

    각 컬럼이 정의된 VALUE_SPECS 범위 내에 있는지 확인.

    Returns:
        dict: 정확성 점수 및 범위 이탈 건수
    """
    n = len(df)
    violations = []

    for col, spec in VALUE_SPECS.items():
        if col not in df.columns:
            continue

        if "allowed" in spec:
            invalid = ~df[col].isin(spec["allowed"])
            count = int(invalid.sum())
            if count > 0:
                violations.append({
                    "column": col,
                    "rule": "allowed_values",
                    "violation_count": count,
                    "description": f"{col}: 허용 값 {spec['allowed']} 외 존재",
                })
        else:
            below_min = (df[col] < spec["min"]).sum()
            above_max = (df[col] > spec["max"]).sum()
            count = int(below_min + above_max)
            if count > 0:
                violations.append({
                    "column": col,
                    "rule": "value_range",
                    "violation_count": count,
                    "description": f"{col}: 범위 [{spec['min']}, {spec['max']}] 이탈",
                })

    total_checks = n * len(VALUE_SPECS)
    total_violations = sum(v["violation_count"] for v in violations)
    score = ((total_checks - total_violations) / total_checks * 100) if total_checks > 0 else 100

    return {
        "dimension": "accuracy",
        "score": round(score, 2),
        "total_checks": total_checks,
        "total_violations": total_violations,
        "details": violations,
    }


def _assign_grade(score):
    """DQM 등급 부여."""
    if score >= 95:
        return "A"
    elif score >= 85:
        return "B"
    elif score >= 70:
        return "C"
    else:
        return "D"


def run_dq_assessment(df):
    """
    전체 데이터 품질 평가 실행. main.py에서 호출.

    4차원 검증을 수행하고 종합 점수 및 등급을 산출한다.

    Returns:
        dict: {
            "completeness": dict,
            "consistency": dict,
            "timeliness": dict,
            "accuracy": dict,
            "overall_score": float,
            "overall_grade": str,
            "summary_df": pd.DataFrame  — 대시보드 표시용 요약
        }
    """
    completeness = check_completeness(df)
    consistency = check_consistency(df)
    timeliness = check_timeliness(df)
    accuracy = check_accuracy(df)

    # 종합 점수 (가중 평균: 완전성 30%, 정합성 25%, 적시성 20%, 정확성 25%)
    overall_score = (
        completeness["score"] * 0.30
        + consistency["score"] * 0.25
        + timeliness["score"] * 0.20
        + accuracy["score"] * 0.25
    )
    overall_score = round(overall_score, 2)
    overall_grade = _assign_grade(overall_score)

    # 요약 DataFrame
    summary_rows = []
    for result in [completeness, consistency, timeliness, accuracy]:
        summary_rows.append({
            "dimension": result["dimension"],
            "score": result["score"],
            "grade": _assign_grade(result["score"]),
        })
    summary_rows.append({
        "dimension": "overall",
        "score": overall_score,
        "grade": overall_grade,
    })

    return {
        "completeness": completeness,
        "consistency": consistency,
        "timeliness": timeliness,
        "accuracy": accuracy,
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "summary_df": pd.DataFrame(summary_rows),
    }
