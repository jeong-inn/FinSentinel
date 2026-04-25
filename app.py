"""
app.py — FinSentinel FDS 대시보드

이상거래탐지시스템(FDS) 운영 대시보드.
금융 거래 모니터링, 서비스 품질 관리, 야간배치 현황, 데이터 품질 시각화.

실행: streamlit run app.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from spc import analyze_spc, control_chart_limits

# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="FinSentinel — FDS 운영 대시보드",
    page_icon="FS",
    layout="wide",
)

st.title("FinSentinel — FDS 운영 대시보드")
st.caption("이상거래탐지 · 서비스 품질 관리 · 야간배치 · 데이터 품질 | Branch: BR_GANGNAM_001")

# ============================================================
# 데이터 로드
# ============================================================

PROCESSED = "data/processed"

SPC_SPECS = {
    "tx_amount":         {"usl": 70.0,  "lsl": 30.0,  "unit": "만원", "label": "거래금액"},
    "response_time_ms":  {"usl": 40.0,  "lsl": 20.0,  "unit": "ms",   "label": "FDS 응답시간"},
    "processing_time_ms": {"usl": 120.0, "lsl": 80.0,  "unit": "ms",   "label": "채널 처리시간"},
}


@st.cache_data
def load_data():
    data = {}
    paths = {
        "logs":         os.path.join(PROCESSED, "analyzed_logs_with_states.csv"),
        "judge":        os.path.join(PROCESSED, "scenario_judgement.csv"),
        "validation":   os.path.join(PROCESSED, "validation_result.csv"),
        "spc":          os.path.join(PROCESSED, "spc_analysis.csv"),
        "report":       os.path.join(PROCESSED, "operator_report.json"),
        "dq":           os.path.join(PROCESSED, "dq_assessment.csv"),
        "settlement":   os.path.join(PROCESSED, "batch_settlement.csv"),
        "str_candidates": os.path.join(PROCESSED, "batch_str_candidates.csv"),
        "reconciliation": os.path.join(PROCESSED, "batch_reconciliation.csv"),
    }
    for key, path in paths.items():
        if os.path.exists(path):
            if key == "report":
                with open(path, "r", encoding="utf-8") as f:
                    data[key] = json.load(f)
            else:
                data[key] = pd.read_csv(path)
    return data


data = load_data()

if not data:
    st.warning("python3 src/main.py를 먼저 실행하세요. data/processed/ 파일이 없습니다.")
    st.stop()

# ============================================================
# 사이드바
# ============================================================

st.sidebar.header("필터")

scenario_ids = sorted(data["logs"]["scenario_id"].unique()) if "logs" in data else []
selected = st.sidebar.selectbox("시나리오", scenario_ids)

# ============================================================
# 상단 메트릭
# ============================================================

if "judge" in data and "validation" in data:
    jr = data["judge"][data["judge"]["scenario_id"] == selected]
    vr = data["validation"][data["validation"]["scenario_id"] == selected]

    if not jr.empty and not vr.empty:
        jr = jr.iloc[0]; vr = vr.iloc[0]

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("최종 판정", jr['final_result'])
        c2.metric("권고 조치", jr["recommended_action_actual"])
        c3.metric("Spec 검증", 'MATCH' if vr['overall_match'] else 'MISMATCH')
        c4.metric("Release Gate", f"{vr.get('release_gate', '-')}")
        c5.metric("Warning 비율", f"{jr['warning_ratio']:.1%}")

# ============================================================
# 탭
# ============================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "타임라인", "서비스 품질 (SPC)", "계좌 분석",
    "판정 요약", "야간배치", "데이터 품질"
])

# ──────────────────────────────────────────────────────────────
# Tab 1: 타임라인 & 상태
# ──────────────────────────────────────────────────────────────

with tab1:
    if "logs" in data:
        sdf = data["logs"][data["logs"]["scenario_id"] == selected].sort_values("timestamp").reset_index(drop=True)

        STATE_COLORS = {
            "NORMAL": "#2ecc71", "WARNING": "#f39c12",
            "CRITICAL": "#e74c3c", "RECOVERY": "#3498db", "FAIL": "#8e44ad",
        }

        fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            subplot_titles=("거래금액 (만원)", "FDS 응답시간 (ms)", "채널 처리시간 (ms)"),
                            vertical_spacing=0.08)

        x = sdf["timestamp"]

        fig.add_trace(go.Scatter(x=x, y=sdf["tx_amount"], mode="lines",
                                 name="tx_amount", line=dict(color="#3498db", width=1)), row=1, col=1)
        if "state" in sdf.columns:
            shown = set()
            for state, color in STATE_COLORS.items():
                mask = sdf["state"] == state
                if mask.any():
                    fig.add_trace(go.Scatter(
                        x=x[mask], y=sdf.loc[mask, "tx_amount"], mode="markers",
                        name=state, marker=dict(color=color, size=4),
                        showlegend=state not in shown,
                    ), row=1, col=1)
                    shown.add(state)

        fig.add_trace(go.Scatter(x=x, y=sdf["response_time_ms"], mode="lines",
                                 name="response_time", line=dict(color="#e67e22", width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=x, y=sdf["processing_time_ms"], mode="lines",
                                 name="processing_time", line=dict(color="#9b59b6", width=1)), row=3, col=1)

        fig.update_layout(height=520, title_text=f"거래 타임라인 — {selected}",
                          margin=dict(t=60, b=20))
        st.plotly_chart(fig, use_container_width=True)

        if "anomaly_reason" in sdf.columns:
            reasons = (sdf["anomaly_reason"].str.split("|").explode()
                       .value_counts().drop("normal", errors="ignore"))
            if not reasons.empty:
                st.subheader("FDS 규칙 탐지 분포")
                st.bar_chart(reasons)

# ──────────────────────────────────────────────────────────────
# Tab 2: 서비스 품질 관리 (SPC/SQM)
# ──────────────────────────────────────────────────────────────

with tab2:
    if "logs" in data:
        sdf = data["logs"][data["logs"]["scenario_id"] == selected].sort_values("timestamp").reset_index(drop=True)

        param_sel = st.selectbox("분석 파라미터", list(SPC_SPECS.keys()),
                                 format_func=lambda k: SPC_SPECS[k]["label"])

        spec = SPC_SPECS[param_sel]
        spc_result = analyze_spc(sdf, col=param_sel, usl=spec["usl"], lsl=spec["lsl"])
        limits = spc_result["limits"]

        ca, cb, cc, cd = st.columns(4)
        cpk_val = spc_result["cpk"]
        ca.metric("Cpk", f"{cpk_val:.3f}" if cpk_val == cpk_val else "N/A",
                  delta="SLA 충족" if (cpk_val == cpk_val and cpk_val >= 1.33) else "SLA 미달",
                  help=">=1.33: 서비스 수준 양호")
        cb.metric("Ppk", f"{spc_result['ppk']:.3f}" if spc_result['ppk'] == spc_result['ppk'] else "N/A")
        cc.metric("Rule1 이탈", spc_result["ooc_summary"].get("rule1_beyond_3sigma", 0),
                  help="UCL/LCL 직접 이탈 포인트 수")
        cd.metric("전체 WE 위반", spc_result["ooc_count"],
                  help="WE Rules 8가지 합산")

        fig_spc = go.Figure()
        x = sdf["timestamp"]
        y = sdf[param_sel].values

        fig_spc.add_trace(go.Scatter(x=x, y=y, mode="lines", name=param_sel,
                                     line=dict(color="#3498db", width=1)))

        for y_val, label, color, dash in [
            (limits.get("ucl"),       "UCL (+3σ)", "red",    "dash"),
            (limits.get("lcl"),       "LCL (-3σ)", "red",    "dash"),
            (limits.get("ucl_2sigma"),"+2σ",       "orange", "dot"),
            (limits.get("lcl_2sigma"),"-2σ",       "orange", "dot"),
            (limits.get("mean"),      "CL (mean)", "green",  "solid"),
            (spec["usl"],             f"USL ({spec['usl']})", "#8e44ad", "longdash"),
            (spec["lsl"],             f"LSL ({spec['lsl']})", "#8e44ad", "longdash"),
        ]:
            if y_val is not None:
                fig_spc.add_hline(y=y_val, line_dash=dash, line_color=color,
                                  annotation_text=label)

        we_df = spc_result["we_rules_df"]
        ooc_mask = we_df["rule1_beyond_3sigma"].values.astype(bool)
        if ooc_mask.any():
            fig_spc.add_trace(go.Scatter(
                x=x[ooc_mask], y=y[ooc_mask], mode="markers",
                name="Rule1 이탈", marker=dict(color="red", size=8, symbol="x")
            ))

        fig_spc.update_layout(
            title=f"X-bar Control Chart — {selected} ({SPC_SPECS[param_sel]['label']})",
            yaxis_title=f"{param_sel} ({spec['unit']})", height=420,
            margin=dict(t=60, b=20),
        )
        st.plotly_chart(fig_spc, use_container_width=True)

        st.subheader("Western Electric Rules 위반 요약")
        rule_labels = {
            "rule1_beyond_3sigma":          "Rule 1: 1점 ±3σ 이탈",
            "rule2_nine_same_side":         "Rule 2: 9점 연속 중심선 한쪽",
            "rule3_six_monotone":           "Rule 3: 6점 연속 단조 변화 (drift)",
            "rule4_fourteen_alternating":   "Rule 4: 14점 교대 상하",
            "rule5_two_of_three_beyond_2sigma": "Rule 5: 3점 중 2점 ±2σ 밖",
            "rule6_four_of_five_beyond_1sigma": "Rule 6: 5점 중 4점 ±1σ 밖",
            "rule7_fifteen_within_1sigma":  "Rule 7: 15점 연속 ±1σ 이내",
            "rule8_eight_beyond_1sigma_both": "Rule 8: 8점 연속 ±1σ 밖 양측",
        }
        ooc_s = spc_result["ooc_summary"]
        rule_rows = [{"규칙": label, "위반 건수": ooc_s.get(key, 0),
                      "상태": "위반" if ooc_s.get(key, 0) > 0 else "정상"}
                     for key, label in rule_labels.items()]
        st.dataframe(pd.DataFrame(rule_rows), use_container_width=True, hide_index=True)

        if "spc" in data:
            spc_all = data["spc"]
            spc_param = spc_all[spc_all["param"] == param_sel].copy()
            if not spc_param.empty:
                st.subheader(f"전 시나리오 Cpk — {SPC_SPECS[param_sel]['label']}")
                cpk_fig = go.Figure(go.Bar(
                    x=spc_param["scenario_id"], y=spc_param["cpk"],
                    marker_color=["#2ecc71" if v >= 1.33 else "#e74c3c"
                                  for v in spc_param["cpk"].fillna(0)],
                    text=spc_param["cpk"].round(3), textposition="outside",
                ))
                cpk_fig.add_hline(y=1.33, line_dash="dash", line_color="green",
                                  annotation_text="Cpk=1.33 (SLA 기준)")
                cpk_fig.update_layout(height=300, yaxis_title="Cpk", margin=dict(t=40, b=20))
                st.plotly_chart(cpk_fig, use_container_width=True)

# ──────────────────────────────────────────────────────────────
# Tab 3: 계좌 분석
# ──────────────────────────────────────────────────────────────

with tab3:
    if "logs" in data and "account_id" in data["logs"].columns:
        sdf = data["logs"][data["logs"]["scenario_id"] == selected].copy()

        st.subheader(f"계좌별 파라미터 분포 — {selected}")

        acct_param = st.selectbox("파라미터 선택", list(SPC_SPECS.keys()),
                                   format_func=lambda k: SPC_SPECS[k]["label"],
                                   key="acct_param")

        acct_stats = sdf.groupby("account_id")[acct_param].agg(["mean", "std"]).reset_index()
        acct_stats.columns = ["account_id", "mean", "std"]

        spec = SPC_SPECS[acct_param]

        fig_w = go.Figure()
        colors = ["#e74c3c" if (m > spec["usl"] or m < spec["lsl"]) else "#3498db"
                  for m in acct_stats["mean"]]
        fig_w.add_trace(go.Bar(
            x=acct_stats["account_id"], y=acct_stats["mean"],
            error_y=dict(type="data", array=acct_stats["std"]),
            marker_color=colors,
            text=acct_stats["mean"].round(2), textposition="outside",
            name="Mean +/- σ",
        ))
        fig_w.add_hline(y=spec["usl"], line_dash="longdash", line_color="#8e44ad",
                        annotation_text=f"USL ({spec['usl']})")
        fig_w.add_hline(y=spec["lsl"], line_dash="longdash", line_color="#8e44ad",
                        annotation_text=f"LSL ({spec['lsl']})")
        fig_w.update_layout(
            title=f"계좌별 평균 {SPC_SPECS[acct_param]['label']}",
            yaxis_title=f"{acct_param} ({spec['unit']})", height=360,
            margin=dict(t=60, b=20),
        )
        st.plotly_chart(fig_w, use_container_width=True)

        # Channel x Account 히트맵
        st.subheader("Channel x Account 히트맵")
        pivot = sdf.pivot_table(values=acct_param, index="channel_id", columns="account_id", aggfunc="mean")
        fig_hm = go.Figure(go.Heatmap(
            z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
            colorscale="RdYlGn_r",
            zmin=spec["lsl"], zmax=spec["usl"],
            text=pivot.values.round(1),
            texttemplate="%{text}",
        ))
        fig_hm.update_layout(
            title=f"Channel x Account 평균 {SPC_SPECS[acct_param]['label']}",
            xaxis_title="Account", yaxis_title="Channel", height=380,
            margin=dict(t=60, b=20),
        )
        st.plotly_chart(fig_hm, use_container_width=True)

        # 계좌별 이상 비율
        st.subheader("계좌별 이상 비율")
        if "anomaly_flag" in sdf.columns:
            acct_anom = sdf.groupby("account_id")["anomaly_flag"].mean().reset_index()
            acct_anom.columns = ["account_id", "anomaly_ratio"]
            fig_ar = go.Figure(go.Bar(
                x=acct_anom["account_id"], y=acct_anom["anomaly_ratio"],
                marker_color=["#e74c3c" if v > 0.1 else "#2ecc71" for v in acct_anom["anomaly_ratio"]],
                text=(acct_anom["anomaly_ratio"] * 100).round(1).astype(str) + "%",
                textposition="outside",
            ))
            fig_ar.update_layout(yaxis_title="Anomaly Ratio", height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig_ar, use_container_width=True)

# ──────────────────────────────────────────────────────────────
# Tab 4: 판정 요약
# ──────────────────────────────────────────────────────────────

with tab4:
    if "judge" in data and "validation" in data:
        st.subheader("전 시나리오 판정 결과")
        merged = data["judge"].merge(data["validation"], on="scenario_id")
        display_cols = ["scenario_id", "final_result", "recommended_action_actual",
                        "warning_ratio", "critical_ratio", "fail_ratio",
                        "expected_final_result", "actual_final_result",
                        "overall_match", "release_gate"]
        display_cols = [c for c in display_cols if c in merged.columns]

        def highlight(row):
            if row.get("final_result") == "FAIL":
                return ["background-color: #ffe0e0"] * len(row)
            elif row.get("final_result") == "PASS_WITH_WARNING":
                return ["background-color: #fff8dc"] * len(row)
            return [""] * len(row)

        st.dataframe(merged[display_cols].style.apply(highlight, axis=1),
                     use_container_width=True, hide_index=True)

    if "report" in data:
        st.subheader(f"운영자 리포트 — {selected}")
        recs = [r for r in data["report"] if r["scenario_id"] == selected]
        if recs:
            rec = recs[0]
            st.json({k: rec[k] for k in
                     ["final_result", "final_reason", "recommended_action",
                      "primary_cause", "secondary_signal", "confidence",
                      "validation", "metrics"]})

# ──────────────────────────────────────────────────────────────
# Tab 5: 야간배치 현황
# ──────────────────────────────────────────────────────────────

with tab5:
    st.subheader("야간배치 처리 현황")

    if "settlement" in data:
        st.markdown("### 일일결산")
        settle = data["settlement"]
        settle_selected = settle[settle["scenario_id"] == selected]
        if not settle_selected.empty:
            st.dataframe(
                settle_selected[["account_id", "total_tx_count",
                                "deposit_amount", "withdrawal_amount",
                                "transfer_amount", "payment_amount",
                                "total_amount", "net_amount"]].round(2),
                use_container_width=True, hide_index=True
            )

    if "str_candidates" in data:
        st.markdown("### STR 후보 (의심거래보고 대상)")
        str_df = data["str_candidates"]
        if not str_df.empty:
            st.dataframe(
                str_df[["scenario_id", "priority", "anomaly_count",
                            "unique_rule_violations", "affected_accounts",
                            "str_status", "reporting_deadline"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.success("STR 후보 없음")

    if "reconciliation" in data:
        st.markdown("### 거래 정합성 검증")
        recon = data["reconciliation"]
        st.dataframe(
            recon[["scenario_id", "raw_tx_count", "settlement_tx_count",
                   "count_match", "amount_difference", "recon_status"]],
            use_container_width=True, hide_index=True
        )

# ──────────────────────────────────────────────────────────────
# Tab 6: 데이터 품질 (DQM)
# ──────────────────────────────────────────────────────────────

with tab6:
    st.subheader("데이터 품질 평가 (DQM)")

    if "dq" in data:
        dq_df = data["dq"]

        grade_colors = {"A": "#2ecc71", "B": "#3498db", "C": "#f39c12", "D": "#e74c3c"}

        cols = st.columns(len(dq_df))
        for i, (_, row) in enumerate(dq_df.iterrows()):
            with cols[i]:
                grade = row["grade"]
                color = grade_colors.get(grade, "#95a5a6")
                st.markdown(f"""
                <div style="text-align: center; padding: 10px; border-radius: 8px; border: 2px solid {color};">
                    <h3 style="color: {color};">{grade}</h3>
                    <p>{row['dimension']}</p>
                    <p style="font-size: 1.2em; font-weight: bold;">{row['score']:.1f}%</p>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("""
        **DQM 4차원 검증 기준** (BIS/금융감독원 가이드라인)
        | 차원 | 설명 | 가중치 |
        |------|------|--------|
        | Completeness | 필수 컬럼 결측치 | 30% |
        | Consistency | 컬럼 간 논리적 일관성 | 25% |
        | Timeliness | 거래 처리 지연 여부 | 20% |
        | Accuracy | 값 범위/포맷 유효성 | 25% |
        """)
    else:
        st.info("DQM 데이터가 없습니다. 파이프라인을 실행하세요.")
