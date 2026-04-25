"""
policy_engine.py — 금융 규제 대응 정책 엔진

금융정보분석원(KoFIU) 및 금융보안원 가이드라인 기반의
이상거래 대응 정책을 결정한다.

대응 액션 체계 (우선순위 순):
  NO_ACTION           : 정상 — 별도 조치 불필요
  ENHANCED_MONITORING : 강화모니터링 — 거래 추이 지속 관찰
  CTR_REVIEW          : 고액거래보고(CTR) 검토 — 1일 1천만원 이상 거래 보고 대상 확인
  STR_REVIEW          : 의심거래보고(STR) 검토 — 자금세탁 의심 분석
  STR_FILING          : 의심거래보고(STR) 제출 — KoFIU 보고
  TRANSACTION_BLOCK   : 거래 차단 — 계좌/채널 거래 즉시 중단
  EMERGENCY_HALT      : 긴급 중단 — 시스템 전면 중단 및 보안팀 에스컬레이션

릴리즈 게이트:
  READY               : 정상 운영
  MONITORING_REQUIRED  : 운영 가능, 모니터링 필요
  REVIEW_REQUIRED      : 릴리즈 보류, 검토 필요
  BLOCKED              : 릴리즈 차단
"""

import pandas as pd

# 대응 액션 우선순위 (높을수록 긴급)
ACTION_PRIORITY = {
    "NO_ACTION": 0,
    "ENHANCED_MONITORING": 1,
    "CTR_REVIEW": 2,
    "STR_REVIEW": 3,
    "STR_FILING": 4,
    "TRANSACTION_BLOCK": 5,
    "EMERGENCY_HALT": 6,
}


def recommend_action_policy(final_result, has_dropout, has_error, has_event, has_resp, has_amount,
                            warning_ratio, critical_ratio, fail_ratio):
    """
    최종 판정 결과와 탐지 이벤트 조합을 바탕으로 대응 액션을 결정한다.

    금융보안원 FDS 대응 절차:
    1. 채널 장애(dropout) → 즉시 거래 차단
    2. 복합 이상(에러+이상거래) → 긴급 중단 에스컬레이션
    3. FAIL 판정 → 심각도에 따라 STR 제출 ~ 긴급 중단
    4. WARNING 판정 → 모니터링 ~ CTR 검토
    """
    if has_dropout:
        return "TRANSACTION_BLOCK"

    if final_result == "FAIL":
        if has_error and has_event:
            return "EMERGENCY_HALT"
        if fail_ratio >= 0.05 and has_resp:
            return "EMERGENCY_HALT"
        if critical_ratio >= 0.10:
            return "EMERGENCY_HALT"
        if has_amount and has_resp:
            return "STR_FILING"
        if has_resp:
            return "STR_REVIEW"
        if has_amount:
            return "STR_FILING"
        return "STR_FILING"

    if final_result == "PASS_WITH_WARNING":
        if critical_ratio > 0:
            return "CTR_REVIEW"
        if warning_ratio >= 0.03:
            return "ENHANCED_MONITORING"
        return "NO_ACTION"

    return "NO_ACTION"


def action_gap(expected_action, actual_action):
    """대응 액션 간 우선순위 차이. 양수 = 과잉대응, 음수 = 과소대응."""
    e = ACTION_PRIORITY.get(expected_action, 0)
    a = ACTION_PRIORITY.get(actual_action, 0)
    return a - e


def decide_gate(final_result, overall_match, warning_ratio, critical_ratio, fail_ratio):
    """
    릴리즈 게이트 판정.
    은행 배포 프로세스의 승인 게이트를 모사.
    """
    if final_result == "FAIL":
        return "BLOCKED"

    if not overall_match:
        return "REVIEW_REQUIRED"

    if critical_ratio > 0 or fail_ratio > 0:
        return "REVIEW_REQUIRED"

    if warning_ratio >= 0.03:
        return "MONITORING_REQUIRED"

    return "READY"


def summarize_quality(validation_df):
    """전체 시나리오 품질 요약 (운영 대시보드용)."""
    total = len(validation_df)
    match_count = int(validation_df["overall_match"].sum())
    mismatch_count = total - match_count
    match_rate = round(match_count / total, 3) if total > 0 else 0.0

    gate_counts = validation_df["release_gate"].value_counts().to_dict()

    return pd.DataFrame([{
        "scenario_total": total,
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "match_rate": match_rate,
        "ready_count": gate_counts.get("READY", 0),
        "monitoring_required_count": gate_counts.get("MONITORING_REQUIRED", 0),
        "review_required_count": gate_counts.get("REVIEW_REQUIRED", 0),
        "blocked_count": gate_counts.get("BLOCKED", 0),
    }])
