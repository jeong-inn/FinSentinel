import json
import pandas as pd
from policy_engine import action_gap, decide_gate


def load_scenario_specs(path="data/scenarios/scenario_specs.json"):
    with open(path, "r", encoding="utf-8") as f:
        specs = json.load(f)
    return pd.DataFrame(specs)


def validate_against_specs(judge_df, spec_df):
    merged = spec_df.merge(judge_df, on="scenario_id", how="left")

    validation_rows = []

    for _, row in merged.iterrows():
        expected_result = row["expected_final_result"]
        actual_result = row["final_result"]

        expected_action = row["recommended_action"]
        actual_action = row["recommended_action_actual"]

        reason_text = str(row["all_reasons"])

        required_keywords = row["required_reason_keywords"]
        if isinstance(required_keywords, str):
            try:
                required_keywords = json.loads(required_keywords)
            except Exception:
                required_keywords = []

        missing_keywords = [kw for kw in required_keywords if kw not in reason_text]

        result_match = expected_result == actual_result
        action_match = expected_action == actual_action
        ratio_match = (
            row["warning_ratio"] <= row["allowed_warning_ratio"] + 1e-9
            and row["critical_ratio"] <= row["allowed_critical_ratio"] + 1e-9
        )
        keyword_match = len(missing_keywords) == 0

        score = 0
        score += 40 if result_match else 0
        score += 25 if action_match else 0
        score += 20 if keyword_match else 0
        score += 15 if ratio_match else 0

        overall_match = result_match and action_match and keyword_match and score >= 85

        gap = action_gap(expected_action, actual_action)

        release_gate = decide_gate(
            final_result=actual_result,
            overall_match=overall_match,
            warning_ratio=row["warning_ratio"],
            critical_ratio=row["critical_ratio"],
            fail_ratio=row["fail_ratio"]
        )

        mismatch_reasons = []
        if not result_match:
            mismatch_reasons.append(f"expected_result={expected_result}, actual_result={actual_result}")
        if not action_match:
            mismatch_reasons.append(f"expected_action={expected_action}, actual_action={actual_action}, gap={gap}")
        if not keyword_match:
            mismatch_reasons.append(f"missing_keywords={missing_keywords}")
        if not ratio_match:
            mismatch_reasons.append(
                f"ratio_exceeded(w={row['warning_ratio']}, c={row['critical_ratio']})"
            )

        validation_rows.append({
            "scenario_id": row["scenario_id"],
            "description": row["description"],
            "expected_final_result": expected_result,
            "actual_final_result": actual_result,
            "expected_action": expected_action,
            "actual_action": actual_action,
            "action_gap": gap,
            "result_match": result_match,
            "action_match": action_match,
            "keyword_match": keyword_match,
            "ratio_match": ratio_match,
            "validation_score": score,
            "overall_match": overall_match,
            "release_gate": release_gate,
            "mismatch_detail": " | ".join(mismatch_reasons) if mismatch_reasons else "MATCH"
        })

    return pd.DataFrame(validation_rows).sort_values("scenario_id").reset_index(drop=True)