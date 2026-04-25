import json
import os
import pandas as pd


def build_operator_report(judge_df, validation_df, root_cause_df, output_path="data/processed/operator_report.json"):
    """
    운영자용 구조화 리포트 생성
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    merged = judge_df.merge(validation_df, on="scenario_id", how="left")
    merged = merged.merge(root_cause_df, on="scenario_id", how="left")

    records = []

    for _, row in merged.iterrows():
        record = {
            "scenario_id": row["scenario_id"],
            "final_result": row["final_result"],
            "final_reason": row["final_reason"],
            "recommended_action": row["recommended_action_actual"],
            "primary_cause": row["primary_cause"],
            "secondary_signal": row["secondary_signal"],
            "confidence": row["confidence"],
            "evidence": row["evidence"],
            "validation": {
                "expected_final_result": row["expected_final_result"],
                "actual_final_result": row["actual_final_result"],
                "expected_action": row["expected_action"],
                "actual_action": row["actual_action"],
                "overall_match": bool(row["overall_match"]),
                "mismatch_detail": row["mismatch_detail"]
            },
            "metrics": {
                "warning_ratio": row["warning_ratio"],
                "critical_ratio": row["critical_ratio"],
                "fail_ratio": row["fail_ratio"]
            }
        }
        records.append(record)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return records


def build_llm_prompt_text(record):
    """
    LLM API 연결용 프롬프트 생성
    """
    return f"""
당신은 금융 거래 모니터링 결과를 해석하는 리스크관리 담당자입니다.
아래 시나리오 결과를 바탕으로 운영자용 리포트를 한국어로 작성하세요.

[시나리오]
- scenario_id: {record['scenario_id']}

[최종 판정]
- final_result: {record['final_result']}
- final_reason: {record['final_reason']}
- recommended_action: {record['recommended_action']}

[원인 분석]
- primary_cause: {record['primary_cause']}
- secondary_signal: {record['secondary_signal']}
- confidence: {record['confidence']}
- evidence: {record['evidence']}

[검증 결과]
- expected_final_result: {record['validation']['expected_final_result']}
- actual_final_result: {record['validation']['actual_final_result']}
- expected_action: {record['validation']['expected_action']}
- actual_action: {record['validation']['actual_action']}
- overall_match: {record['validation']['overall_match']}
- mismatch_detail: {record['validation']['mismatch_detail']}

[정량 지표]
- warning_ratio: {record['metrics']['warning_ratio']}
- critical_ratio: {record['metrics']['critical_ratio']}
- fail_ratio: {record['metrics']['fail_ratio']}

다음 형식으로 작성하세요:
1. 결과 요약
2. 판정 근거
3. 원인 후보
4. 권장 조치
5. 추가 확인 필요 사항
""".strip()


def save_llm_prompts(records, output_path="data/processed/llm_prompts.txt"):
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write("=" * 80 + "\n")
            f.write(build_llm_prompt_text(record))
            f.write("\n\n")

    return output_path
