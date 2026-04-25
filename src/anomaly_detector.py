"""
anomaly_detector.py — FDS 규칙 기반 이상거래 탐지 엔진

금융보안원 FDS 운영 가이드라인의 오용탐지(Misuse Detection) 규칙을 구현한다.
각 거래에 대해 7개 기본 규칙 + 2개 FDS 강화 규칙을 적용하여
anomaly_flag(0/1)와 anomaly_reason(탐지 사유)을 부여한다.

규칙 체계:
  [기본 규칙]
  R1. 고액 거래 — tx_amount ≥ 65만원 (CTR 보고 기준 근접)
  R2. 금액 급변 — |tx_amount_diff| ≥ 8 (rolling mean 대비)
  R3. 처리시간 초과 — processing_time_ms ≥ 135ms
  R4. 처리시간 급증 — processing_time_diff ≥ 15ms
  R5. 거래 오류 — error_code ≠ 0
  R6. FDS 응답 장애 — response_time_ms ≤ 1ms (dropout)
  R7. 이상거래 플래그 — fraud_flag = 1

  [FDS 강화 규칙]
  R8. 야간 고액 거래 — 심야(00~05시) + tx_amount ≥ 60만원
  R9. 고위험 고객 이체 — CDD 등급 ≥ 4 + TRANSFER + tx_amount ≥ 58만원
"""

import numpy as np
import pandas as pd


def detect_anomalies(df):
    """
    벡터화된 규칙 기반 이상 탐지.
    iterrows 대신 numpy 연산으로 10,000 row 기준 ~50x 성능 향상.

    Returns:
        DataFrame with anomaly_flag (0/1), anomaly_reason (str) 추가
    """
    df = df.copy()
    n = len(df)

    # 각 규칙별 boolean mask (vectorized)
    r1_amount_high = df["tx_amount"].values >= 65
    r2_amount_spike = np.abs(df["tx_amount_diff"].values) >= 8
    r3_proc_high = df["processing_time_ms"].values >= 135
    r4_proc_jump = df["processing_time_diff"].values >= 15
    r5_error = df["error_code"].values != 0
    r6_dropout = df["response_time_ms"].values <= 1
    r7_fraud = df["fraud_flag"].values == 1

    # FDS 강화 규칙
    r8_night_high = np.zeros(n, dtype=bool)
    r9_risk_transfer = np.zeros(n, dtype=bool)

    if "tx_hour" in df.columns:
        hours = df["tx_hour"].values
        r8_night_high = ((hours >= 0) & (hours <= 5)) & (df["tx_amount"].values >= 60)

    if "customer_risk_level" in df.columns and "tx_type" in df.columns:
        r9_risk_transfer = (
            (df["customer_risk_level"].values >= 4)
            & (df["tx_type"].values == "TRANSFER")
            & (df["tx_amount"].values >= 58)
        )

    # 규칙-레이블 매핑
    rule_map = [
        (r1_amount_high, "amount_high"),
        (r2_amount_spike, "amount_spike"),
        (r3_proc_high, "processing_time_high"),
        (r4_proc_jump, "processing_time_jump"),
        (r5_error, "tx_error_detected"),
        (r6_dropout, "response_dropout"),
        (r7_fraud, "fraud_event"),
        (r8_night_high, "fds_night_high_amount"),
        (r9_risk_transfer, "fds_high_risk_transfer"),
    ]

    # anomaly_reason 조합
    reasons = []
    any_flag = np.zeros(n, dtype=bool)

    for mask, label in rule_map:
        any_flag |= mask

    for i in range(n):
        row_reasons = [label for mask, label in rule_map if mask[i]]
        reasons.append("|".join(row_reasons) if row_reasons else "normal")

    df["anomaly_flag"] = any_flag.astype(int)
    df["anomaly_reason"] = reasons

    return df


def summarize_anomalies(df):
    """
    시나리오별 이상 탐지 건수 및 규칙별 분포 요약.
    """
    summary = (
        df.groupby("scenario_id")["anomaly_flag"]
        .sum()
        .reset_index()
        .rename(columns={"anomaly_flag": "anomaly_count"})
    )
    return summary


def get_rule_distribution(df):
    """
    전체 데이터셋의 규칙별 탐지 건수 분포.
    FDS 운영 리포트용.
    """
    all_reasons = "|".join(df[df["anomaly_flag"] == 1]["anomaly_reason"].tolist())
    rule_labels = [
        "amount_high", "amount_spike", "processing_time_high",
        "processing_time_jump", "tx_error_detected", "response_dropout",
        "fraud_event", "fds_night_high_amount", "fds_high_risk_transfer",
    ]
    distribution = {}
    for label in rule_labels:
        distribution[label] = all_reasons.count(label)
    return distribution
