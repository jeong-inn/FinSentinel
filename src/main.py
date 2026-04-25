"""
main.py — FinSentinel FDS 파이프라인 오케스트레이터

금융 이상거래탐지시스템(FDS)의 전체 파이프라인을 실행한다.

파이프라인 단계:
  1. 데이터 로드 & 전처리      (preprocess.py)
  2. 규칙 기반 이상 탐지        (anomaly_detector.py)
  3. 상태 머신 분류             (state_engine.py)
  4. 시나리오 최종 판정          (judge.py)
  5. 시나리오 검증              (validator.py)
  6. 서비스 품질 분석 (SPC/SQM) (spc.py)
  7. 원인 분석                  (root_cause.py)
  8. 데이터 품질 검증 (DQM)     (dq_monitor.py)       ← NEW
  9. 야간배치 처리              (batch_processor.py)   ← NEW
 10. 운영자 리포트 & LLM       (operator_report.py, llm_reporter.py)
 11. PostgreSQL 저장            (db_writer.py)
"""

import os
import sys
import logging
from datetime import datetime

import pandas as pd

# project root 기준 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from preprocess import preprocess_logs
from anomaly_detector import detect_anomalies, summarize_anomalies
from state_engine import assign_states, summarize_states, final_state_per_scenario
from judge import judge_scenarios
from validator import load_scenario_specs, validate_against_specs
from root_cause import analyze_root_causes
from operator_report import build_operator_report, save_llm_prompts
from llm_reporter import generate_llm_reports
from policy_engine import summarize_quality
from spc import analyze_spc_by_scenario
from dq_monitor import run_dq_assessment
from batch_processor import run_all_batches
from db_writer import write_all

# ================================================================
# 로깅 설정
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FinSentinel")

# ================================================================
# 서비스 품질 관리 파라미터 (SLA 규격 한계)
# ================================================================
TX_AMOUNT_USL    = 70.0;   TX_AMOUNT_LSL    = 30.0   # 거래금액: 정상 30~70 만원
RESPONSE_USL     = 40.0;   RESPONSE_LSL     = 20.0   # FDS 응답: 정상 20~40 ms
PROC_TIME_USL    = 120.0;  PROC_TIME_LSL    = 80.0   # 처리시간: 정상 80~120 ms


def _path(*parts):
    return os.path.join(PROJECT_ROOT, *parts)


def main():
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("  FinSentinel FDS Pipeline 시작")
    logger.info("=" * 60)

    os.makedirs(_path("data", "processed"), exist_ok=True)

    # =========================================================
    # STAGE 1: 데이터 로드 & 전처리
    # =========================================================
    logger.info("[1/11] 데이터 로드 & 전처리")
    df = preprocess_logs(_path("data", "raw", "transaction_logs.csv"))

    # =========================================================
    # STAGE 2: FDS 규칙 기반 이상 탐지
    # =========================================================
    logger.info("[2/11] FDS 규칙 기반 이상 탐지 (9개 규칙)")
    df = detect_anomalies(df)

    # =========================================================
    # STAGE 3: 상태 머신 분류
    # =========================================================
    logger.info("[3/11] 거래 상태 머신 분류")
    df = assign_states(df)

    df.to_csv(_path("data", "processed", "analyzed_logs_with_states.csv"), index=False)

    anomaly_summary = summarize_anomalies(df)
    state_summary = summarize_states(df)
    final_states = final_state_per_scenario(df)

    # =========================================================
    # STAGE 4: 시나리오 최종 판정
    # =========================================================
    logger.info("[4/11] 시나리오 최종 판정")
    judge_df = judge_scenarios(df)
    judge_df.to_csv(_path("data", "processed", "scenario_judgement.csv"), index=False)

    # =========================================================
    # STAGE 5: 시나리오 검증 (scenario_specs 대비)
    # =========================================================
    logger.info("[5/11] 시나리오 검증")
    spec_df = load_scenario_specs(_path("data", "scenarios", "scenario_specs.json"))
    validation_df = validate_against_specs(judge_df, spec_df)
    validation_df.to_csv(_path("data", "processed", "validation_result.csv"), index=False)

    quality_df = summarize_quality(validation_df)
    quality_df.to_csv(_path("data", "processed", "quality_summary.csv"), index=False)

    # =========================================================
    # STAGE 6: 서비스 품질 분석 (SPC/SQM)
    # =========================================================
    logger.info("[6/11] 서비스 품질 분석 — 3개 파라미터 Cpk/Ppk/WE Rules")
    spc_amount = analyze_spc_by_scenario(df, col="tx_amount",         usl=TX_AMOUNT_USL, lsl=TX_AMOUNT_LSL)
    spc_resp   = analyze_spc_by_scenario(df, col="response_time_ms",  usl=RESPONSE_USL,  lsl=RESPONSE_LSL)
    spc_proc   = analyze_spc_by_scenario(df, col="processing_time_ms", usl=PROC_TIME_USL, lsl=PROC_TIME_LSL)

    for _df, _param in [(spc_amount, "tx_amount"), (spc_resp, "response_time_ms"), (spc_proc, "processing_time_ms")]:
        _df.insert(1, "param", _param)

    spc_df = pd.concat([spc_amount, spc_resp, spc_proc], ignore_index=True)
    spc_df.to_csv(_path("data", "processed", "spc_analysis.csv"), index=False)

    # =========================================================
    # STAGE 7: 원인 분석
    # =========================================================
    logger.info("[7/11] 원인 분석")
    root_cause_df = analyze_root_causes(df, judge_df)
    root_cause_df.to_csv(_path("data", "processed", "root_cause_analysis.csv"), index=False)

    # =========================================================
    # STAGE 8: 데이터 품질 검증 (DQM)
    # =========================================================
    logger.info("[8/11] 데이터 품질 검증 — 4차원 DQM")
    dq_result = run_dq_assessment(df)
    dq_result["summary_df"].to_csv(_path("data", "processed", "dq_assessment.csv"), index=False)

    # =========================================================
    # STAGE 9: 야간배치 처리
    # =========================================================
    logger.info("[9/11] 야간배치 — 일일결산/한도점검/STR후보/정합성검증")
    batch_result = run_all_batches(df, judge_df)
    batch_result["settlement"].to_csv(_path("data", "processed", "batch_settlement.csv"), index=False)
    batch_result["limit_check"].to_csv(_path("data", "processed", "batch_limit_check.csv"), index=False)
    batch_result["str_candidates"].to_csv(_path("data", "processed", "batch_str_candidates.csv"), index=False)
    batch_result["reconciliation"].to_csv(_path("data", "processed", "batch_reconciliation.csv"), index=False)

    # =========================================================
    # STAGE 10: 운영자 리포트 & LLM
    # =========================================================
    logger.info("[10/11] 운영자 리포트 생성")
    records = build_operator_report(
        judge_df=judge_df,
        validation_df=validation_df,
        root_cause_df=root_cause_df,
        output_path=_path("data", "processed", "operator_report.json")
    )

    save_llm_prompts(
        records,
        output_path=_path("data", "processed", "llm_prompts.txt")
    )

    generate_llm_reports(
        records,
        output_path=_path("data", "processed", "llm_reports.json"),
        model="gpt-4o",
        max_reports=1
    )

    # =========================================================
    # STAGE 11: PostgreSQL 저장
    # =========================================================
    logger.info("[11/11] PostgreSQL 저장")
    write_all(df, judge_df, validation_df, spc_df, root_cause_df,
              batch_result=batch_result, dq_result=dq_result)

    # =========================================================
    # 결과 출력
    # =========================================================
    elapsed = (datetime.now() - start_time).total_seconds()

    print("\n" + "=" * 70)
    print("  FinSentinel FDS Pipeline 결과")
    print("=" * 70)

    print("\n[최종 판정]")
    print(judge_df[[
        "scenario_id", "final_result", "recommended_action_actual",
        "warning_ratio", "critical_ratio", "fail_ratio"
    ]].to_string(index=False))

    print("\n[검증 결과]")
    print(validation_df[[
        "scenario_id", "expected_final_result", "actual_final_result",
        "expected_action", "actual_action", "action_gap",
        "validation_score", "overall_match", "release_gate"
    ]].to_string(index=False))

    print("\n[품질 요약]")
    print(quality_df.to_string(index=False))

    print("\n[데이터 품질 (DQM)]")
    print(dq_result["summary_df"].to_string(index=False))

    print("\n[야간배치 요약]")
    bs = batch_result["batch_summary"]
    print(f"  결산 계좌: {bs['settlement_accounts']}건")
    print(f"  한도 초과: {bs['limit_alerts']}건 | CTR 대상: {bs['ctr_targets']}건")
    print(f"  STR 후보: {bs['str_candidates']}건 (긴급: {bs['str_urgent']}건)")
    print(f"  정합성: PASS {bs['recon_pass']}건 / MISMATCH {bs['recon_mismatch']}건")

    if len(batch_result["str_candidates"]) > 0:
        print("\n[STR 후보 목록]")
        print(batch_result["str_candidates"][[
            "scenario_id", "anomaly_count", "priority", "str_status"
        ]].to_string(index=False))

    print("\n[서비스 품질 (SPC/SQM)]")
    spc_display_cols = ["scenario_id", "param", "cpk", "ppk", "rule1_count", "ooc_count", "ucl", "lcl"]
    print(spc_df[spc_display_cols].to_string(index=False))

    print(f"\n[원인 분석]")
    print(root_cause_df.to_string(index=False))

    print("\n" + "=" * 70)
    print(f"  파이프라인 완료 (소요시간: {elapsed:.1f}초)")
    print("=" * 70)


if __name__ == "__main__":
    main()
