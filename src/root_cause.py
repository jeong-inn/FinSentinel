import pandas as pd


def analyze_root_causes(df, judge_df):
    """
    scenario별 root cause 구조화
    출력 컬럼:
    - primary_cause
    - secondary_signal
    - confidence
    - evidence
    """
    rows = []

    for _, jrow in judge_df.iterrows():
        scenario_id = jrow["scenario_id"]
        g = df[df["scenario_id"] == scenario_id].copy()

        reason_text = str(jrow["all_reasons"])

        has_dropout = "response_dropout" in reason_text
        has_error = "tx_error_detected" in reason_text
        has_event = "fraud_event" in reason_text
        has_resp_jump = "processing_time_jump" in reason_text
        has_resp_high = "processing_time_high" in reason_text
        has_amount_high = "amount_high" in reason_text
        has_amount_spike = "amount_spike" in reason_text

        if has_dropout:
            primary_cause = "Channel response dropout (system/network failure)"
            secondary_signal = "response_time_ms unavailable"
            confidence = "High"
        elif has_amount_high and (has_resp_jump or has_resp_high):
            primary_cause = "Persistent high-value transactions with processing degradation"
            secondary_signal = "processing_time_ms increase"
            confidence = "High"
        elif has_error and has_event:
            primary_cause = "Combined fault with fraud-event-triggered instability"
            secondary_signal = "repeated tx_error + fraud_flag"
            confidence = "High"
        elif has_resp_jump or has_resp_high:
            primary_cause = "System processing time degradation"
            secondary_signal = "processing_time_ms abnormal trend"
            confidence = "Medium"
        elif has_amount_high:
            primary_cause = "Persistent transaction amount above threshold"
            secondary_signal = "tx_amount above threshold"
            confidence = "Medium"
        elif has_amount_spike:
            primary_cause = "Transient amount spike (market volatility or anomalous transaction)"
            secondary_signal = "short tx_amount abnormal excursion"
            confidence = "Low"
        elif has_error:
            primary_cause = "Repeated transaction error pattern (network or gateway issue)"
            secondary_signal = "error_code recurrence"
            confidence = "Medium"
        else:
            primary_cause = "No significant abnormality"
            secondary_signal = "none"
            confidence = "Low"

        evidence_parts = []

        if has_amount_high:
            evidence_parts.append("amount_high_detected")
        if has_amount_spike:
            evidence_parts.append("amount_spike_detected")
        if has_resp_jump or has_resp_high:
            evidence_parts.append("processing_time_abnormal")
        if has_error:
            evidence_parts.append("tx_error_detected")
        if has_event:
            evidence_parts.append("fraud_event_detected")
        if has_dropout:
            evidence_parts.append("response_dropout_detected")

        evidence_parts.append(f"warning_ratio={jrow['warning_ratio']}")
        evidence_parts.append(f"critical_ratio={jrow['critical_ratio']}")
        evidence_parts.append(f"fail_ratio={jrow['fail_ratio']}")

        rows.append({
            "scenario_id": scenario_id,
            "primary_cause": primary_cause,
            "secondary_signal": secondary_signal,
            "confidence": confidence,
            "evidence": " | ".join(evidence_parts)
        })

    return pd.DataFrame(rows).sort_values("scenario_id").reset_index(drop=True)
