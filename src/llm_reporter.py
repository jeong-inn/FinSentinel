import os
import json
from openai import OpenAI


def build_messages(record):
    system_prompt = (
        "당신은 테스트 결과를 해석하는 품질/검증 엔지니어다. "
        "출력은 한국어로 작성하고, 과장 없이 기술적 근거 중심으로 작성하라. "
        "반드시 JSON 형식으로만 응답하라."
    )

    user_prompt = f"""
아래 시나리오 결과를 바탕으로 운영자/엔지니어용 리포트를 작성하라.

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

반드시 아래 JSON 스키마로만 응답:
{{
  "scenario_id": "...",
  "summary": "...",
  "judgement_basis": ["...", "..."],
  "root_cause_hypothesis": "...",
  "recommended_actions": ["...", "..."],
  "retest_needed": true,
  "engineering_review_needed": false,
  "operator_note": "..."
}}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_fallback_report(record, error_message):
    return {
        "scenario_id": record["scenario_id"],
        "summary": f"LLM 보고서 생성 실패. 기본 규칙 기반 결과를 사용합니다. ({error_message})",
        "judgement_basis": [
            f"final_result={record['final_result']}",
            f"recommended_action={record['recommended_action']}",
            f"primary_cause={record['primary_cause']}"
        ],
        "root_cause_hypothesis": record["primary_cause"],
        "recommended_actions": [record["recommended_action"]],
        "retest_needed": record["recommended_action"] in ["RETEST_RECOMMENDED", "RETEST_AND_ANALYZE"],
        "engineering_review_needed": record["recommended_action"] in ["ENGINEERING_REVIEW", "SHUTDOWN_REQUIRED", "FAIL_LOCK"],
        "operator_note": "API 응답 지연 또는 실패로 인해 fallback report를 생성했습니다."
    }


def generate_llm_reports(records, output_path="data/processed/llm_reports.json", model="gpt-5", max_reports=1):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[LLM] OPENAI_API_KEY 없음 — fallback report 생성", flush=True)
        fallback_results = [build_fallback_report(r, "API key not set") for r in (records[:max_reports] if max_reports else records)]
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            import json
            json.dump(fallback_results, f, ensure_ascii=False, indent=2)
        return fallback_results

    client = OpenAI(api_key=api_key)

    if max_reports is not None:
        target_records = records[:max_reports]
    else:
        target_records = records

    results = []

    for idx, record in enumerate(target_records, start=1):
        print(f"[LLM] generating report {idx}/{len(target_records)} - {record['scenario_id']}", flush=True)

        try:
            messages = build_messages(record)

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                timeout=30,
            )

            content = response.choices[0].message.content
            parsed = json.loads(content)
            results.append(parsed)

            print(f"[LLM] done - {record['scenario_id']}", flush=True)

        except Exception as e:
            print(f"[LLM] failed - {record['scenario_id']} - {str(e)}", flush=True)
            fallback = build_fallback_report(record, str(e))
            results.append(fallback)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results