"""
judge.py — 시나리오별 최종 판정 엔진

각 시나리오의 전체 상태 흐름을 분석하여 최종 판정(PASS/PASS_WITH_WARNING/FAIL)을
결정하고, 금융 규제 대응 정책(STR/CTR/거래차단 등)을 권고한다.

판정 기준:
  PASS             : 이상 징후 없이 정상 운영
  PASS_WITH_WARNING: 일시적 이상이 있었으나 자가 회복됨
  FAIL             : 지속적/심각한 이상으로 운영 불가 판정

판정 후 policy_engine의 recommend_action_policy()를 호출하여
KoFIU 보고 의무 대상 여부를 판단한다.
"""

import pandas as pd
from policy_engine import recommend_action_policy


def judge_scenarios(df):
    """
    시나리오별 최종 판정을 수행한다.

    로직:
    1. 상태(state) 분포 집계 (FAIL/CRITICAL/WARNING/NORMAL/RECOVERY)
    2. FAIL 존재 → 즉시 FAIL 판정
    3. WARNING 비율 ≥ 40% → FAIL (장시간 이상 지속)
    4. CRITICAL 비율 ≥ 2% → FAIL (치명적 이상 반복)
    5. 복합 이상 조합 → FAIL
    6. WARNING/CRITICAL 존재 → PASS_WITH_WARNING
    7. 그 외 → PASS
    """
    results = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()
        total_count = len(g)

        state_counts = g["state"].value_counts().to_dict()

        fail_count = state_counts.get("FAIL", 0)
        critical_count = state_counts.get("CRITICAL", 0)
        warning_count = state_counts.get("WARNING", 0)

        fail_ratio = fail_count / total_count
        critical_ratio = critical_count / total_count
        warning_ratio = warning_count / total_count

        all_reasons = "|".join(g["anomaly_reason"].astype(str).tolist())

        has_dropout = "response_dropout" in all_reasons
        has_error = "tx_error_detected" in all_reasons
        has_event = "fraud_event" in all_reasons
        has_resp = ("processing_time_high" in all_reasons) or ("processing_time_jump" in all_reasons)
        has_amount = ("amount_high" in all_reasons) or ("amount_spike" in all_reasons)

        # 최종 판정
        if fail_count > 0:
            final_result = "FAIL"

            if has_dropout:
                final_reason = "채널 FDS 응답 dropout 발생으로 거래 차단 필요"
            elif has_error and has_event:
                final_reason = "복합 이상(거래에러+이상거래이벤트) 발생으로 긴급 중단 필요"
            elif has_resp:
                final_reason = "시스템 처리시간 누적 초과로 서비스 품질 기준 미달"
            elif has_amount:
                final_reason = "고액 이상거래 지속 발생으로 STR 보고 검토 필요"
            else:
                final_reason = "치명 이상 상태 발생으로 최종 FAIL 판정"

        elif warning_ratio >= 0.40:
            final_result = "FAIL"

            if has_amount and has_resp:
                final_reason = "거래금액 이상과 처리시간 초과가 장시간 지속 — STR 보고 대상"
            elif has_amount:
                final_reason = "거래금액 이상 상태가 장시간 지속 — 자금세탁 의심"
            elif has_resp:
                final_reason = "시스템 처리시간 초과 장시간 지속 — 채널 성능 점검 필요"
            else:
                final_reason = "경고 상태 장시간 지속으로 운영 불가 판정"

        elif critical_ratio >= 0.02:
            final_result = "FAIL"

            if has_error and has_event:
                final_reason = "복합 치명 이상 반복 발생 — 보안팀 에스컬레이션 필요"
            else:
                final_reason = "치명 이상 상태 반복 발생으로 최종 FAIL 판정"

        elif (has_amount and has_resp and has_error) or (has_amount and has_event):
            final_result = "FAIL"
            final_reason = "복합 이상 조합 확인 — 다중 규칙 동시 위반"

        elif critical_count > 0 or warning_count > 0:
            final_result = "PASS_WITH_WARNING"

            if critical_count > 0:
                final_reason = "치명 이상 징후가 있었으나 자가 회복 — 강화 모니터링 권고"
            else:
                final_reason = "경고 수준 이상 징후가 있었으나 자가 회복 — 추이 관찰 필요"

        else:
            final_result = "PASS"
            final_reason = "정상 범위 유지 — 별도 조치 불필요"

        # 대응 정책 결정
        recommended_action_actual = recommend_action_policy(
            final_result=final_result,
            has_dropout=has_dropout,
            has_error=has_error,
            has_event=has_event,
            has_resp=has_resp,
            has_amount=has_amount,
            warning_ratio=warning_ratio,
            critical_ratio=critical_ratio,
            fail_ratio=fail_ratio
        )

        results.append({
            "scenario_id": scenario_id,
            "total_count": total_count,
            "fail_count": fail_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "fail_ratio": round(fail_ratio, 3),
            "critical_ratio": round(critical_ratio, 3),
            "warning_ratio": round(warning_ratio, 3),
            "final_result": final_result,
            "final_reason": final_reason,
            "recommended_action_actual": recommended_action_actual,
            "all_reasons": all_reasons
        })

    return pd.DataFrame(results).sort_values("scenario_id").reset_index(drop=True)
