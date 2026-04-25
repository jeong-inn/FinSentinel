"""
batch_processor.py — 야간배치 처리 모듈

한국 시중은행의 야간배치(Nightly Batch) 프로세스를 모사한다.
실제 은행에서는 Spring Batch 등을 사용하지만, 여기서는 pandas로 구현.

배치 작업 목록:
  1. 일일결산 (Daily Settlement)
     - 계좌별 거래 집계 (입금/출금/이체/결제)
     - 순 거래금액 산출
  2. 한도 점검 (Limit Check)
     - 1일 거래한도 초과 계좌 식별
     - CTR(고액거래보고) 대상 자동 추출
  3. STR 후보 추출 (Suspicious Transaction Report Candidates)
     - 이상 탐지 결과 기반 의심거래 후보 생성
     - KoFIU 보고 대상 사전 필터링
  4. 거래 정합성 검증 (Reconciliation)
     - 시나리오 내 거래 건수/금액 교차 검증
     - 불일치 건 식별

실행 시점: main.py 파이프라인의 이상탐지 완료 후
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ================================================================
# 배치 설정 (실제 은행에서는 YAML/DB에서 로드)
# ================================================================
DAILY_TX_LIMIT = 5000.0  # 1일 거래한도 (만원) — 1일 5천만원
CTR_THRESHOLD = 1000.0   # CTR 보고 기준 (만원) — 1일 1천만원 이상 현금거래
STR_ANOMALY_THRESHOLD = 3  # STR 후보 기준: 시나리오 내 이상 탐지 3건 이상


def run_daily_settlement(df):
    """
    일일결산 배치: 계좌별 거래 유형별 집계.

    실제 은행 야간배치에서는 이 결과로:
    - 계좌 잔액 갱신
    - 이자 계산 기초 데이터 생성
    - 일계표 작성

    Returns:
        pd.DataFrame: 계좌별 거래 유형별 건수/금액 집계
    """
    settlement_records = []

    for scenario_id, scenario_group in df.groupby("scenario_id"):
        for account_id, acc_group in scenario_group.groupby("account_id"):
            record = {
                "scenario_id": scenario_id,
                "account_id": account_id,
                "settlement_date": _extract_settlement_date(acc_group),
                "total_tx_count": len(acc_group),
            }

            # 거래 유형별 집계
            if "tx_type" in acc_group.columns:
                for tx_type in ["DEPOSIT", "WITHDRAWAL", "TRANSFER", "PAYMENT"]:
                    type_mask = acc_group["tx_type"] == tx_type
                    record[f"{tx_type.lower()}_count"] = int(type_mask.sum())
                    record[f"{tx_type.lower()}_amount"] = round(
                        acc_group.loc[type_mask, "tx_amount"].sum(), 2
                    )
            else:
                record["deposit_count"] = 0
                record["deposit_amount"] = 0.0
                record["withdrawal_count"] = 0
                record["withdrawal_amount"] = 0.0
                record["transfer_count"] = 0
                record["transfer_amount"] = 0.0
                record["payment_count"] = 0
                record["payment_amount"] = 0.0

            record["total_amount"] = round(acc_group["tx_amount"].sum(), 2)
            record["avg_amount"] = round(acc_group["tx_amount"].mean(), 2)
            record["max_amount"] = round(acc_group["tx_amount"].max(), 2)
            record["min_amount"] = round(acc_group["tx_amount"].min(), 2)

            # 순 거래금액 (입금 - 출금 - 이체 - 결제)
            net = record.get("deposit_amount", 0) - (
                record.get("withdrawal_amount", 0)
                + record.get("transfer_amount", 0)
                + record.get("payment_amount", 0)
            )
            record["net_amount"] = round(net, 2)

            settlement_records.append(record)

    return pd.DataFrame(settlement_records)


def run_limit_check(settlement_df):
    """
    한도 점검 배치: 일일 거래한도 초과 및 CTR 보고 대상 식별.

    CTR(Currency Transaction Report):
    - 특정금융거래정보법 제4조에 의거
    - 1일 1천만원 이상 현금거래 시 금융정보분석원(KoFIU)에 자동 보고

    Returns:
        pd.DataFrame: 한도 초과 / CTR 대상 계좌 목록
    """
    limit_records = []

    for _, row in settlement_df.iterrows():
        total = row["total_amount"]

        limit_exceeded = total > DAILY_TX_LIMIT
        ctr_target = total > CTR_THRESHOLD

        if limit_exceeded or ctr_target:
            limit_records.append({
                "scenario_id": row["scenario_id"],
                "account_id": row["account_id"],
                "total_amount": total,
                "daily_limit": DAILY_TX_LIMIT,
                "limit_exceeded": limit_exceeded,
                "limit_excess_amount": round(max(0, total - DAILY_TX_LIMIT), 2),
                "ctr_target": ctr_target,
                "ctr_report_required": ctr_target,
                "check_status": "ALERT" if limit_exceeded else "CTR_REVIEW",
            })

    if not limit_records:
        return pd.DataFrame(columns=[
            "scenario_id", "account_id", "total_amount", "daily_limit",
            "limit_exceeded", "limit_excess_amount", "ctr_target",
            "ctr_report_required", "check_status"
        ])

    return pd.DataFrame(limit_records)


def run_str_candidate_extraction(df, judge_df):
    """
    STR 후보 추출 배치: 의심거래보고 후보 사전 필터링.

    STR(Suspicious Transaction Report):
    - 특정금융거래정보법 제4조의2에 의거
    - 자금세탁 또는 테러자금조달 의심 거래 시 KoFIU에 보고

    STR 후보 선정 기준:
    1. 시나리오 내 이상 탐지 건수 ≥ STR_ANOMALY_THRESHOLD
    2. 최종 판정이 FAIL인 시나리오
    3. 복합 이상 패턴 (다중 규칙 동시 위반)

    Returns:
        pd.DataFrame: STR 후보 목록 (우선순위 포함)
    """
    str_candidates = []

    anomaly_by_scenario = (
        df[df["anomaly_flag"] == 1]
        .groupby("scenario_id")
        .agg(
            anomaly_count=("anomaly_flag", "sum"),
            unique_reasons=("anomaly_reason", lambda x: len(set("|".join(x).split("|")) - {"normal"})),
            affected_accounts=("account_id", "nunique"),
        )
        .reset_index()
    )

    for _, row in anomaly_by_scenario.iterrows():
        sid = row["scenario_id"]

        # 최종 판정 확인
        judge_row = judge_df[judge_df["scenario_id"] == sid]
        final_result = judge_row["final_result"].values[0] if len(judge_row) > 0 else "UNKNOWN"
        action = judge_row["recommended_action_actual"].values[0] if len(judge_row) > 0 else "UNKNOWN"

        # STR 후보 판정
        is_str_candidate = (
            row["anomaly_count"] >= STR_ANOMALY_THRESHOLD
            or final_result == "FAIL"
        )

        if not is_str_candidate:
            continue

        # 우선순위 산정
        priority_score = 0
        if final_result == "FAIL":
            priority_score += 50
        if row["unique_reasons"] >= 3:
            priority_score += 30
        if row["affected_accounts"] >= 3:
            priority_score += 20
        priority_score += min(row["anomaly_count"], 50)

        if priority_score >= 80:
            priority = "URGENT"
        elif priority_score >= 50:
            priority = "HIGH"
        elif priority_score >= 30:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        str_candidates.append({
            "scenario_id": sid,
            "anomaly_count": int(row["anomaly_count"]),
            "unique_rule_violations": int(row["unique_reasons"]),
            "affected_accounts": int(row["affected_accounts"]),
            "final_result": final_result,
            "recommended_action": action,
            "priority_score": priority_score,
            "priority": priority,
            "str_status": "PENDING_REVIEW",
            "reporting_deadline": "T+3 영업일",
        })

    if not str_candidates:
        return pd.DataFrame(columns=[
            "scenario_id", "anomaly_count", "unique_rule_violations",
            "affected_accounts", "final_result", "recommended_action",
            "priority_score", "priority", "str_status", "reporting_deadline"
        ])

    return pd.DataFrame(str_candidates).sort_values("priority_score", ascending=False).reset_index(drop=True)


def run_reconciliation(df, settlement_df):
    """
    거래 정합성 검증 배치: 원장과 집계 데이터 교차 검증.

    실제 은행에서는:
    - 원거래 로그 ↔ 일일결산 ↔ 계정계 원장 3자 대사
    - 불일치 시 자동 알림 → 수동 조사

    Returns:
        pd.DataFrame: 시나리오별 정합성 검증 결과
    """
    recon_records = []

    for scenario_id in df["scenario_id"].unique():
        raw_group = df[df["scenario_id"] == scenario_id]
        settle_group = settlement_df[settlement_df["scenario_id"] == scenario_id]

        raw_total_count = len(raw_group)
        raw_total_amount = round(raw_group["tx_amount"].sum(), 2)

        settle_total_count = int(settle_group["total_tx_count"].sum()) if len(settle_group) > 0 else 0
        settle_total_amount = round(settle_group["total_amount"].sum(), 2) if len(settle_group) > 0 else 0

        count_match = raw_total_count == settle_total_count
        amount_diff = abs(raw_total_amount - settle_total_amount)
        amount_match = amount_diff < 0.01  # 부동소수점 허용 오차

        recon_records.append({
            "scenario_id": scenario_id,
            "raw_tx_count": raw_total_count,
            "settlement_tx_count": settle_total_count,
            "count_match": count_match,
            "raw_total_amount": raw_total_amount,
            "settlement_total_amount": settle_total_amount,
            "amount_difference": round(amount_diff, 4),
            "amount_match": amount_match,
            "recon_status": "PASS" if (count_match and amount_match) else "MISMATCH",
        })

    return pd.DataFrame(recon_records)


def run_all_batches(df, judge_df):
    """
    전체 야간배치 실행. main.py에서 호출.

    Returns:
        dict: {
            "settlement": pd.DataFrame,
            "limit_check": pd.DataFrame,
            "str_candidates": pd.DataFrame,
            "reconciliation": pd.DataFrame,
            "batch_summary": dict
        }
    """
    # 1. 일일결산
    settlement_df = run_daily_settlement(df)

    # 2. 한도 점검
    limit_df = run_limit_check(settlement_df)

    # 3. STR 후보 추출
    str_df = run_str_candidate_extraction(df, judge_df)

    # 4. 정합성 검증
    recon_df = run_reconciliation(df, settlement_df)

    # 배치 요약
    batch_summary = {
        "batch_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "settlement_accounts": len(settlement_df),
        "limit_alerts": int(limit_df["limit_exceeded"].sum()) if len(limit_df) > 0 else 0,
        "ctr_targets": int(limit_df["ctr_target"].sum()) if len(limit_df) > 0 else 0,
        "str_candidates": len(str_df),
        "str_urgent": int((str_df["priority"] == "URGENT").sum()) if len(str_df) > 0 else 0,
        "recon_pass": int((recon_df["recon_status"] == "PASS").sum()),
        "recon_mismatch": int((recon_df["recon_status"] == "MISMATCH").sum()),
    }

    return {
        "settlement": settlement_df,
        "limit_check": limit_df,
        "str_candidates": str_df,
        "reconciliation": recon_df,
        "batch_summary": batch_summary,
    }


def _extract_settlement_date(group):
    """거래 그룹에서 결산 일자 추출."""
    if "tx_datetime" in group.columns:
        return group["tx_datetime"].iloc[0][:10]
    return "2025-01-06"
