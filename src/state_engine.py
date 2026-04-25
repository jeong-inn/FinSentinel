"""
state_engine.py — 거래 상태 머신 (Transaction State Machine)

각 거래의 이상 탐지 결과를 바탕으로 실시간 상태를 분류한다.
은행 FDS의 거래 모니터링 상태 전이 로직을 구현.

상태 정의:
  NORMAL   : 정상 거래 — 이상 징후 없음
  WARNING  : 주의 — 단일 규칙 위반 (모니터링 대상)
  CRITICAL : 위험 — 복합 규칙 위반 또는 심각한 단일 위반
  RECOVERY : 회복 — 이상 후 정상 복귀 진행 중
  FAIL     : 실패 — 채널 장애 또는 CRITICAL 30회 연속 (에스컬레이션 대상)

상태 전이 규칙:
  NORMAL → WARNING   : 단일 이상 탐지
  NORMAL → CRITICAL  : 복합 이상 탐지 (dropout, error+event 등)
  WARNING → CRITICAL : 복합 이상 조건 충족
  CRITICAL → FAIL    : 30회 연속 CRITICAL 지속
  ANY_ANOMALY → RECOVERY : 이상 후 정상 거래 발생
  RECOVERY → NORMAL  : 이상 없이 정상 유지
"""

import pandas as pd


def assign_states(df):
    """
    anomaly 결과를 바탕으로 각 거래의 실시간 상태를 분류한다.
    시나리오별로 독립 실행 (각 시나리오는 별도의 상태 머신).
    """
    result = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()
        states = []

        prev_state = "NORMAL"
        critical_streak = 0

        for _, row in g.iterrows():
            reason = row["anomaly_reason"]

            is_dropout = "response_dropout" in reason
            is_error = "tx_error_detected" in reason
            is_event = "fraud_event" in reason
            is_resp_high = "processing_time_high" in reason or "processing_time_jump" in reason
            is_amount_high = "amount_high" in reason or "amount_spike" in reason

            if row["anomaly_flag"] == 0:
                # 정상 거래: 이전 이상 상태에서 회복 중이면 RECOVERY
                if prev_state in ["WARNING", "CRITICAL", "FAIL", "RECOVERY"]:
                    state = "RECOVERY"
                else:
                    state = "NORMAL"
                critical_streak = 0

            else:
                # FDS 응답 장애 → 즉시 FAIL
                if is_dropout:
                    state = "FAIL"
                    critical_streak += 1

                # 복합 이상 → CRITICAL
                elif is_error and (is_resp_high or is_amount_high or is_event):
                    state = "CRITICAL"
                    critical_streak += 1

                elif is_resp_high and is_amount_high:
                    state = "CRITICAL"
                    critical_streak += 1

                # 단일 이상 → WARNING
                elif is_error:
                    state = "WARNING"
                    critical_streak = 0

                elif is_resp_high or is_amount_high or is_event:
                    state = "WARNING"
                    critical_streak = 0

                else:
                    state = "WARNING"
                    critical_streak = 0

            # CRITICAL 30회 연속 → FAIL 에스컬레이션
            if critical_streak >= 30:
                state = "FAIL"

            states.append(state)
            prev_state = state

        g["state"] = states
        result.append(g)

    out = pd.concat(result, ignore_index=True)
    return out


def summarize_states(df):
    """시나리오별 상태 분포 요약."""
    summary = (
        df.groupby(["scenario_id", "state"])
        .size()
        .reset_index(name="count")
        .sort_values(["scenario_id", "state"])
    )
    return summary


def final_state_per_scenario(df):
    """시나리오별 마지막 거래의 상태 추출."""
    final_df = (
        df.sort_values(["scenario_id", "timestamp"])
        .groupby("scenario_id")
        .tail(1)[["scenario_id", "state"]]
        .rename(columns={"state": "final_state"})
        .reset_index(drop=True)
    )
    return final_df
