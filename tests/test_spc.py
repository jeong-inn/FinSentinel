"""
test_spc.py — SPC 모듈 단위 테스트
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spc import analyze_spc, calc_cpk, control_chart_limits, western_electric_rules


# ============================================================
# calc_cpk
# ============================================================

def test_cpk_centered_process():
    """거래 파라미터가 규격 중앙에 있으면 Cpk가 양수여야 한다."""
    np.random.seed(0)
    data = np.random.normal(50, 3, 500)
    cpk = calc_cpk(data, usl=70, lsl=30)
    assert cpk > 0, "centered process Cpk should be positive"


def test_cpk_exceeds_1_33_for_capable_process():
    """σ가 충분히 작으면 Cpk >= 1.33."""
    np.random.seed(0)
    data = np.random.normal(50, 1.0, 500)
    cpk = calc_cpk(data, usl=70, lsl=30)
    assert cpk >= 1.33, f"Cpk should be >= 1.33 for tight process, got {cpk}"


def test_cpk_less_than_1_for_incapable_process():
    """분산이 크면 Cpk < 1."""
    np.random.seed(0)
    data = np.random.normal(50, 15, 500)
    cpk = calc_cpk(data, usl=70, lsl=30)
    assert cpk < 1.0, f"Cpk should be < 1 for incapable process, got {cpk}"


def test_cpk_one_sided_shift():
    """평균이 USL 쪽으로 치우치면 Cpk가 감소한다."""
    data = np.random.normal(65, 2, 300)
    cpk = calc_cpk(data, usl=70, lsl=30)
    assert cpk < 1.33, "shifted mean should reduce Cpk"


def test_cpk_returns_nan_for_zero_sigma():
    """σ=0이면 NaN을 반환해야 한다."""
    data = [50.0] * 100
    cpk = calc_cpk(data, usl=70, lsl=30)
    assert np.isnan(cpk), "zero sigma should yield NaN Cpk"


def test_cpk_invalid_spec():
    """USL <= LSL이면 NaN 반환."""
    data = np.random.normal(50, 3, 100)
    cpk = calc_cpk(data, usl=30, lsl=70)
    assert np.isnan(cpk)


# ============================================================
# control_chart_limits
# ============================================================

def test_control_chart_limits_structure():
    data = np.random.normal(50, 3, 200)
    limits = control_chart_limits(data)
    assert "mean" in limits
    assert "ucl" in limits
    assert "lcl" in limits
    assert "sigma" in limits


def test_control_chart_ucl_gt_mean_gt_lcl():
    data = np.random.normal(50, 3, 200)
    limits = control_chart_limits(data)
    assert limits["ucl"] > limits["mean"] > limits["lcl"]


def test_control_chart_3sigma_distance():
    data = np.random.normal(50, 3, 5000)
    limits = control_chart_limits(data)
    sigma = limits["sigma"]
    assert abs((limits["ucl"] - limits["mean"]) - 3 * sigma) < 0.01


# ============================================================
# western_electric_rules
# ============================================================

def test_we_rule1_detects_beyond_3sigma():
    """Rule 1: 3σ 이탈 포인트 탐지."""
    data = np.zeros(50)
    data[25] = 10.0
    we = western_electric_rules(data)
    assert we["rule1_beyond_3sigma"].iloc[25] == 1


def test_we_rule2_nine_same_side():
    """Rule 2: 9점 연속 중심선 한쪽."""
    mean = 50.0
    data = [mean + 2] * 9 + [mean - 1] * 10
    we = western_electric_rules(data)
    assert we["rule2_nine_same_side"].iloc[8] == 1


def test_we_rule3_six_monotone_increasing():
    """Rule 3: 연속 6점 단조 증가 탐지."""
    data = list(range(1, 7)) + [5] * 10
    we = western_electric_rules(data)
    assert we["rule3_six_monotone"].iloc[5] == 1


def test_we_rules_output_shape():
    """출력 컬럼 수와 row 수가 입력과 동일해야 한다."""
    data = np.random.normal(0, 1, 100)
    we = western_electric_rules(data)
    assert len(we) == 100
    assert "ooc_any" in we.columns
    assert we.shape[1] == 9


def test_we_ooc_any_is_union():
    """ooc_any는 모든 rule의 OR이어야 한다."""
    data = np.random.normal(50, 3, 200)
    we = western_electric_rules(data)
    rule_cols = [c for c in we.columns if c.startswith("rule")]
    manual_any = we[rule_cols].any(axis=1).astype(int)
    pd.testing.assert_series_equal(we["ooc_any"], manual_any, check_names=False)


# ============================================================
# analyze_spc (통합 진입점)
# ============================================================

def test_analyze_spc_returns_required_keys():
    df = pd.DataFrame({"tx_amount": np.random.normal(50, 2, 300)})
    result = analyze_spc(df, col="tx_amount", usl=70, lsl=30)
    assert "cpk" in result
    assert "ppk" in result
    assert "limits" in result
    assert "we_rules_df" in result
    assert "ooc_count" in result
    assert "ooc_summary" in result


def test_analyze_spc_ooc_count_nonnegative():
    df = pd.DataFrame({"tx_amount": np.random.normal(50, 2, 200)})
    result = analyze_spc(df, col="tx_amount", usl=70, lsl=30)
    assert result["ooc_count"] >= 0


def test_analyze_spc_cpk_ppk_same_for_stable():
    """안정된 프로세스에서 Cpk ≈ Ppk 여야 한다."""
    np.random.seed(42)
    df = pd.DataFrame({"tx_amount": np.random.normal(50, 2, 1000)})
    result = analyze_spc(df, col="tx_amount", usl=70, lsl=30)
    assert abs(result["cpk"] - result["ppk"]) < 0.3, "Cpk and Ppk should be close for stable process"
