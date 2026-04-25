"""
test_pipeline.py — FDS 파이프라인 통합 테스트

테스트 범위:
  - 데이터 생성 구조 검증
  - FDS 이상 탐지 규칙 검증
  - 상태 머신 전이 검증
  - 시나리오 판정 검증
  - 서비스 품질(SPC) 검증
  - 원인 분석 검증
  - 야간배치 처리 검증
  - 데이터 품질(DQM) 검증
"""

import sys
import os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from generate_logs import build_scenarios
from preprocess import add_rolling_features
from anomaly_detector import detect_anomalies
from state_engine import assign_states
from judge import judge_scenarios
from validator import load_scenario_specs, validate_against_specs
from root_cause import analyze_root_causes
from spc import analyze_spc_by_scenario
from batch_processor import run_all_batches
from dq_monitor import run_dq_assessment


@pytest.fixture(scope="module")
def pipeline_df():
    """전체 파이프라인을 한 번 실행하여 결과를 공유."""
    df = build_scenarios()
    df = add_rolling_features(df)
    df = detect_anomalies(df)
    df = assign_states(df)
    return df


@pytest.fixture(scope="module")
def judge_df(pipeline_df):
    return judge_scenarios(pipeline_df)


# ============================================================
# 데이터 생성 검증
# ============================================================

def test_scenario_count(pipeline_df):
    """10개 시나리오가 생성되어야 한다."""
    assert pipeline_df["scenario_id"].nunique() == 10


def test_rows_per_scenario(pipeline_df):
    """시나리오당 1000 rows."""
    counts = pipeline_df.groupby("scenario_id").size()
    assert all(c == 1000 for c in counts), f"Row counts: {counts.to_dict()}"


def test_required_columns(pipeline_df):
    """필수 컬럼이 모두 존재해야 한다."""
    required = [
        "timestamp", "branch_id", "account_id", "channel_id",
        "scenario_id", "tx_amount", "response_time_ms", "processing_time_ms",
        "error_code", "fraud_flag", "anomaly_flag", "anomaly_reason", "state"
    ]
    for col in required:
        assert col in pipeline_df.columns, f"Missing column: {col}"


def test_new_financial_columns(pipeline_df):
    """금융 거래 부가 컬럼이 존재해야 한다."""
    financial_cols = ["tx_datetime", "tx_hour", "tx_type", "customer_risk_level"]
    for col in financial_cols:
        assert col in pipeline_df.columns, f"Missing financial column: {col}"


def test_tx_type_values(pipeline_df):
    """거래 유형이 4가지 중 하나여야 한다."""
    valid_types = {"DEPOSIT", "WITHDRAWAL", "TRANSFER", "PAYMENT"}
    actual_types = set(pipeline_df["tx_type"].unique())
    assert actual_types == valid_types, f"Unexpected tx_types: {actual_types}"


def test_customer_risk_distribution(pipeline_df):
    """고객 위험등급이 1~5 범위여야 한다."""
    risk_values = pipeline_df["customer_risk_level"].unique()
    assert all(1 <= r <= 5 for r in risk_values)


# ============================================================
# FDS 이상 탐지 검증
# ============================================================

def test_s1_no_anomalies(pipeline_df):
    """S1 정상 시나리오: 이상 탐지 비율이 매우 낮아야 한다."""
    s1 = pipeline_df[pipeline_df["scenario_id"] == "S1"]
    anomaly_ratio = s1["anomaly_flag"].mean()
    assert anomaly_ratio < 0.05, f"S1 anomaly ratio too high: {anomaly_ratio}"


def test_s6_has_dropout(pipeline_df):
    """S6: response_dropout이 탐지되어야 한다."""
    s6 = pipeline_df[pipeline_df["scenario_id"] == "S6"]
    reasons = "|".join(s6["anomaly_reason"].tolist())
    assert "response_dropout" in reasons


def test_s8_has_multiple_anomalies(pipeline_df):
    """S8 복합 이상: 여러 종류의 이상이 탐지되어야 한다."""
    s8 = pipeline_df[pipeline_df["scenario_id"] == "S8"]
    reasons = "|".join(s8["anomaly_reason"].tolist())
    assert "fraud_event" in reasons
    assert "tx_error_detected" in reasons


def test_s3_has_amount_high(pipeline_df):
    """S3 고액 이상: amount_high가 탐지되어야 한다."""
    s3 = pipeline_df[pipeline_df["scenario_id"] == "S3"]
    reasons = "|".join(s3["anomaly_reason"].tolist())
    assert "amount_high" in reasons


# ============================================================
# 상태 분류 검증
# ============================================================

def test_s1_all_normal(pipeline_df):
    """S1: 대부분 NORMAL 상태."""
    s1 = pipeline_df[pipeline_df["scenario_id"] == "S1"]
    normal_ratio = (s1["state"] == "NORMAL").mean()
    assert normal_ratio > 0.90


def test_s6_has_fail_state(pipeline_df):
    """S6: FAIL 상태가 존재해야 한다 (채널 dropout)."""
    s6 = pipeline_df[pipeline_df["scenario_id"] == "S6"]
    assert "FAIL" in s6["state"].values


def test_state_values_valid(pipeline_df):
    """모든 state 값이 유효해야 한다."""
    valid_states = {"NORMAL", "WARNING", "CRITICAL", "RECOVERY", "FAIL"}
    actual_states = set(pipeline_df["state"].unique())
    assert actual_states.issubset(valid_states), f"Invalid states: {actual_states - valid_states}"


# ============================================================
# 판정 검증
# ============================================================

def test_s1_pass(judge_df):
    """S1: PASS 판정."""
    s1 = judge_df[judge_df["scenario_id"] == "S1"]
    assert s1.iloc[0]["final_result"] == "PASS"


def test_s6_fail(judge_df):
    """S6: FAIL 판정 (채널 장애)."""
    s6 = judge_df[judge_df["scenario_id"] == "S6"]
    assert s6.iloc[0]["final_result"] == "FAIL"


def test_s2_pass_with_warning(judge_df):
    """S2: PASS_WITH_WARNING 판정 (스파이크 후 회복)."""
    s2 = judge_df[judge_df["scenario_id"] == "S2"]
    assert s2.iloc[0]["final_result"] == "PASS_WITH_WARNING"


def test_s6_transaction_block(judge_df):
    """S6: 거래 차단(TRANSACTION_BLOCK) 액션이 권고되어야 한다."""
    s6 = judge_df[judge_df["scenario_id"] == "S6"]
    assert s6.iloc[0]["recommended_action_actual"] == "TRANSACTION_BLOCK"


def test_s8_emergency_halt(judge_df):
    """S8: 긴급 중단(EMERGENCY_HALT) 액션이 권고되어야 한다."""
    s8 = judge_df[judge_df["scenario_id"] == "S8"]
    assert s8.iloc[0]["recommended_action_actual"] == "EMERGENCY_HALT"


# ============================================================
# 서비스 품질 (SPC/SQM) 검증
# ============================================================

def test_spc_s1_cpk_high(pipeline_df):
    """S1 정상: Cpk가 1.33 이상이어야 한다 (서비스 품질 양호)."""
    spc = analyze_spc_by_scenario(pipeline_df, col="tx_amount", usl=70.0, lsl=30.0)
    s1_cpk = spc[spc["scenario_id"] == "S1"].iloc[0]["cpk"]
    assert s1_cpk >= 1.33, f"S1 Cpk should be >= 1.33, got {s1_cpk}"


def test_spc_s3_cpk_low(pipeline_df):
    """S3 드리프트: Cpk가 1.0 미만이어야 한다 (서비스 품질 미달)."""
    spc = analyze_spc_by_scenario(pipeline_df, col="tx_amount", usl=70.0, lsl=30.0)
    s3_cpk = spc[spc["scenario_id"] == "S3"].iloc[0]["cpk"]
    assert s3_cpk < 1.0, f"S3 Cpk should be < 1.0, got {s3_cpk}"


# ============================================================
# 원인 분석 검증
# ============================================================

def test_root_cause_s6_dropout(pipeline_df, judge_df):
    """S6: dropout 원인이 식별되어야 한다."""
    rc = analyze_root_causes(pipeline_df, judge_df)
    s6 = rc[rc["scenario_id"] == "S6"]
    assert "dropout" in s6.iloc[0]["primary_cause"].lower()


# ============================================================
# 야간배치 검증
# ============================================================

def test_batch_settlement(pipeline_df, judge_df):
    """일일결산 배치: 모든 시나리오×계좌 조합이 결산되어야 한다."""
    result = run_all_batches(pipeline_df, judge_df)
    settlement = result["settlement"]
    assert len(settlement) == 50  # 10 scenarios × 5 accounts


def test_batch_str_candidates(pipeline_df, judge_df):
    """STR 후보 추출: FAIL 시나리오가 STR 후보에 포함되어야 한다."""
    result = run_all_batches(pipeline_df, judge_df)
    str_df = result["str_candidates"]
    assert len(str_df) > 0
    # S6 (FAIL) should be in STR candidates
    assert "S6" in str_df["scenario_id"].values


def test_batch_reconciliation(pipeline_df, judge_df):
    """정합성 검증: 원장과 결산 건수가 일치해야 한다."""
    result = run_all_batches(pipeline_df, judge_df)
    recon = result["reconciliation"]
    assert all(recon["count_match"])


# ============================================================
# 데이터 품질 (DQM) 검증
# ============================================================

def test_dq_completeness(pipeline_df):
    """완전성: 필수 컬럼에 결측치가 없어야 한다."""
    dq = run_dq_assessment(pipeline_df)
    assert dq["completeness"]["score"] == 100.0


def test_dq_overall_grade(pipeline_df):
    """종합 등급이 A 또는 B여야 한다."""
    dq = run_dq_assessment(pipeline_df)
    assert dq["overall_grade"] in ["A", "B"]


def test_dq_summary_df_structure(pipeline_df):
    """DQM 요약 DataFrame 구조 검증."""
    dq = run_dq_assessment(pipeline_df)
    summary = dq["summary_df"]
    assert len(summary) == 5  # 4 dimensions + overall
    assert "dimension" in summary.columns
    assert "score" in summary.columns
    assert "grade" in summary.columns
