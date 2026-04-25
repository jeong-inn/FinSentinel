"""
spc.py — 서비스 품질 관리 (SQM) 모듈

Statistical Process Control(SPC) 기법을 금융 서비스 품질 관리에 적용한다.
거래 금액, FDS 응답시간, 채널 처리시간 등의 서비스 지표가
규격 한계(Spec Limit) 내에서 안정적으로 유지되는지 통계적으로 평가한다.

적용 지표:
  - Cpk / Ppk: 서비스 수준 능력 지수
    · Cpk ≥ 1.33: 서비스 품질 양호
    · Cpk < 1.00: 서비스 품질 미달 — 개선 필요
  - X-bar Control Chart: 관리도 기반 추이 모니터링
  - Western Electric Rules: 8가지 관리 이탈(OOC) 패턴 탐지

금융 서비스 품질 관리 적용 예:
  tx_amount       : 거래 금액 정상 범위 (30~70만원)
  response_time_ms: FDS 응답시간 SLA (20~40ms)
  processing_time_ms: 채널 처리시간 SLA (80~120ms)
"""

import numpy as np
import pandas as pd


# ============================================================
# 서비스 수준 능력 지수
# ============================================================

def calc_cpk(data, usl, lsl):
    """
    Cpk: 단기 서비스 수준 능력 지수 (within-subgroup σ 기반)

    Cpk = min(Cpu, Cpl)
      Cpu = (USL - mean) / (3σ)
      Cpl = (mean - LSL) / (3σ)

    Cpk ≥ 1.33: 서비스 안정 (규격 내 운영)
    Cpk < 1.00: 서비스 미달 (SLA 위반 위험)
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0 or usl <= lsl:
        return float("nan")

    mean = arr.mean()
    sigma = arr.std(ddof=1) if len(arr) > 1 else 0.0
    if sigma == 0:
        return float("nan")

    cpu = (usl - mean) / (3 * sigma)
    cpl = (mean - lsl) / (3 * sigma)
    return round(min(cpu, cpl), 4)


def calc_ppk(data, usl, lsl):
    """
    Ppk: 장기 서비스 성능 지수 (overall σ 기반)
    Cpk와 달리 전체 분포의 σ를 사용 — 서비스 안정성까지 반영.
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0 or usl <= lsl:
        return float("nan")

    mean = arr.mean()
    sigma = arr.std(ddof=0)
    if sigma == 0:
        return float("nan")

    ppu = (usl - mean) / (3 * sigma)
    ppl = (mean - lsl) / (3 * sigma)
    return round(min(ppu, ppl), 4)


# ============================================================
# X-bar Control Chart 관리한계
# ============================================================

def control_chart_limits(data):
    """
    X-bar Chart의 관리한계 계산.
    UCL = mean + 3σ  (Upper Control Limit — 관리 상한)
    LCL = mean - 3σ  (Lower Control Limit — 관리 하한)

    금융 서비스에서는 SLA 위반 조기 경고에 활용.

    Returns:
        dict: {"mean", "sigma", "ucl", "lcl",
               "ucl_2sigma", "lcl_2sigma",
               "ucl_1sigma", "lcl_1sigma"}
    """
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return {}

    mean = arr.mean()
    sigma = arr.std(ddof=1) if len(arr) > 1 else 0.0

    return {
        "mean": round(mean, 4),
        "sigma": round(sigma, 4),
        "ucl": round(mean + 3 * sigma, 4),
        "lcl": round(mean - 3 * sigma, 4),
        "ucl_2sigma": round(mean + 2 * sigma, 4),
        "lcl_2sigma": round(mean - 2 * sigma, 4),
        "ucl_1sigma": round(mean + 1 * sigma, 4),
        "lcl_1sigma": round(mean - 1 * sigma, 4),
    }


# ============================================================
# Western Electric Rules (WE Rules) — 8가지 OOC 탐지
# ============================================================

def western_electric_rules(data, mean=None, sigma=None):
    """
    Western Electric Handbook (1956)의 8가지 OOC 판정 규칙.
    금융 서비스 품질 관리에서 거래 파라미터의 비정상 패턴을 탐지한다.

    규칙 목록:
      Rule 1: 1점이 ±3σ 밖 (극단 이탈)
      Rule 2: 연속 9점이 중심선 한쪽 (편향)
      Rule 3: 연속 6점이 단조 증감 (추세)
      Rule 4: 연속 14점이 교대 반복 (진동)
      Rule 5: 연속 3점 중 2점이 ±2σ 밖 (불안정)
      Rule 6: 연속 5점 중 4점이 ±1σ 밖 (치우침)
      Rule 7: 연속 15점이 ±1σ 이내 (과도 안정 — 데이터 조작 의심)
      Rule 8: 연속 8점이 ±1σ 밖 양측 (혼합 분포)

    Args:
        data: array-like (시계열 파라미터 값)
        mean: float, 기준 평균 (None이면 데이터에서 계산)
        sigma: float, 기준 표준편차 (None이면 데이터에서 계산)

    Returns:
        pd.DataFrame: 각 row마다 rule1~rule8 (0/1), ooc_any (0/1)
    """
    arr = np.asarray(data, dtype=float)
    n = len(arr)

    if mean is None:
        mean = np.nanmean(arr)
    if sigma is None:
        sigma = np.nanstd(arr, ddof=1) if n > 1 else 0.0

    if sigma == 0:
        sigma = 1e-9

    z = (arr - mean) / sigma

    rule1 = np.zeros(n, dtype=int)
    rule2 = np.zeros(n, dtype=int)
    rule3 = np.zeros(n, dtype=int)
    rule4 = np.zeros(n, dtype=int)
    rule5 = np.zeros(n, dtype=int)
    rule6 = np.zeros(n, dtype=int)
    rule7 = np.zeros(n, dtype=int)
    rule8 = np.zeros(n, dtype=int)

    for i in range(n):
        # Rule 1: 1점이 ±3σ 밖
        if abs(z[i]) > 3:
            rule1[i] = 1

        # Rule 2: 연속 9점이 중심선 한쪽에만 위치
        if i >= 8:
            window = z[i - 8:i + 1]
            if all(w > 0 for w in window) or all(w < 0 for w in window):
                rule2[i] = 1

        # Rule 3: 연속 6점이 단조 증가 또는 단조 감소
        if i >= 5:
            window = arr[i - 5:i + 1]
            diffs = np.diff(window)
            if all(d > 0 for d in diffs) or all(d < 0 for d in diffs):
                rule3[i] = 1

        # Rule 4: 연속 14점이 교대로 상하 반복
        if i >= 13:
            window = arr[i - 13:i + 1]
            diffs = np.diff(window)
            alternating = all(
                (diffs[j] > 0) != (diffs[j + 1] > 0)
                for j in range(len(diffs) - 1)
            )
            if alternating:
                rule4[i] = 1

        # Rule 5: 연속 3점 중 2점이 ±2σ 밖 (같은 쪽)
        if i >= 2:
            window = z[i - 2:i + 1]
            above2 = sum(1 for w in window if w > 2)
            below2 = sum(1 for w in window if w < -2)
            if above2 >= 2 or below2 >= 2:
                rule5[i] = 1

        # Rule 6: 연속 5점 중 4점이 ±1σ 밖 (같은 쪽)
        if i >= 4:
            window = z[i - 4:i + 1]
            above1 = sum(1 for w in window if w > 1)
            below1 = sum(1 for w in window if w < -1)
            if above1 >= 4 or below1 >= 4:
                rule6[i] = 1

        # Rule 7: 연속 15점이 ±1σ 이내 (과도하게 안정적)
        if i >= 14:
            window = z[i - 14:i + 1]
            if all(abs(w) < 1 for w in window):
                rule7[i] = 1

        # Rule 8: 연속 8점이 모두 ±1σ 밖 (양측)
        if i >= 7:
            window = z[i - 7:i + 1]
            if all(abs(w) > 1 for w in window):
                rule8[i] = 1

    ooc_any = np.clip(rule1 + rule2 + rule3 + rule4 + rule5 + rule6 + rule7 + rule8, 0, 1)

    return pd.DataFrame({
        "rule1_beyond_3sigma": rule1,
        "rule2_nine_same_side": rule2,
        "rule3_six_monotone": rule3,
        "rule4_fourteen_alternating": rule4,
        "rule5_two_of_three_beyond_2sigma": rule5,
        "rule6_four_of_five_beyond_1sigma": rule6,
        "rule7_fifteen_within_1sigma": rule7,
        "rule8_eight_beyond_1sigma_both": rule8,
        "ooc_any": ooc_any,
    })


# ============================================================
# 통합 분석 진입점
# ============================================================

def analyze_spc(df, col, usl, lsl):
    """
    서비스 품질 지표 전체 분석 (단일 진입점).

    Args:
        df: pd.DataFrame (col 컬럼 포함)
        col: str, 분석 대상 컬럼명 (예: "tx_amount", "response_time_ms")
        usl: float, 규격 상한 (Upper Spec Limit)
        lsl: float, 규격 하한 (Lower Spec Limit)

    Returns:
        dict: cpk, ppk, limits, we_rules_df, ooc_count, ooc_summary
    """
    data = df[col].values
    limits = control_chart_limits(data)
    mean = limits.get("mean")
    sigma = limits.get("sigma")

    cpk = calc_cpk(data, usl, lsl)
    ppk = calc_ppk(data, usl, lsl)
    we_df = western_electric_rules(data, mean=mean, sigma=sigma)

    ooc_summary = {
        col_name: int(we_df[col_name].sum())
        for col_name in we_df.columns
        if col_name != "ooc_any"
    }

    return {
        "cpk": cpk,
        "ppk": ppk,
        "limits": limits,
        "we_rules_df": we_df,
        "ooc_count": int(we_df["ooc_any"].sum()),
        "ooc_summary": ooc_summary,
    }


def analyze_spc_by_scenario(df, col, usl, lsl):
    """
    시나리오별 서비스 품질 분석 수행.

    Returns:
        pd.DataFrame: scenario_id별 Cpk, Ppk, OOC 건수 등
    """
    results = []
    for scenario_id, group in df.groupby("scenario_id"):
        spc = analyze_spc(group, col, usl, lsl)
        results.append({
            "scenario_id": scenario_id,
            "cpk": spc["cpk"],
            "ppk": spc["ppk"],
            "ooc_count": spc["ooc_count"],
            "rule1_count": spc["ooc_summary"].get("rule1_beyond_3sigma", 0),
            "ucl": spc["limits"].get("ucl"),
            "lcl": spc["limits"].get("lcl"),
            "mean": spc["limits"].get("mean"),
            "sigma": spc["limits"].get("sigma"),
            **{k: v for k, v in spc["ooc_summary"].items()},
        })

    return pd.DataFrame(results).sort_values("scenario_id").reset_index(drop=True)
