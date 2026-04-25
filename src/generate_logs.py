"""
generate_logs.py — 금융 거래 FDS 시뮬레이션 로그 생성

이상거래탐지시스템(FDS) 검증용 합성 거래 로그를 생성한다.
금융보안원 FDS 운영 가이드라인의 거래 모니터링 항목을 반영하되,
np.random.seed(42)로 결과 재현성을 보장한다.

구조:
  1 Branch × 5 Accounts × 8 Channels × 25 transactions = 1,000 rows/scenario
  10 scenarios × 1,000 = 총 10,000 rows

거래 파라미터:
  tx_amount           : 거래 금액 (만원), 정상범위 30~70
  response_time_ms    : FDS 응답시간 (ms), 금융보안원 권고 실시간 30ms 이내
  processing_time_ms  : 채널 처리시간 (ms), 인터넷뱅킹 기준 80~120ms
  error_code          : 거래 오류 코드 (0=정상)
  fraud_flag          : 이상거래 플래그 (0/1)

부가 정보:
  tx_datetime         : 거래 일시 (ISO 8601)
  tx_hour             : 거래 시각 (0~23)
  tx_type             : 거래 유형 (DEPOSIT/WITHDRAWAL/TRANSFER/PAYMENT)
  customer_risk_level : 고객확인(CDD) 위험등급 (1=LOW ~ 5=CRITICAL)
  counterparty_id     : 이체 상대방 식별자 (TRANSFER 유형만)

⚠️ 주의: seed=42 고정. 이 파일을 수정하면 전체 synthetic 결과가 변경됨.
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

np.random.seed(42)

# 구조 상수
N_ACCOUNTS = 5
N_CHANNELS = 8
N_TX = 25  # 계좌당 채널당 거래 수
BRANCH_ID = "BR_GANGNAM_001"

# 거래 유형 분포 (한국 시중은행 일반 거래 비율 기반)
TX_TYPES = ["DEPOSIT", "WITHDRAWAL", "TRANSFER", "PAYMENT"]
TX_TYPE_PROBS = [0.20, 0.25, 0.15, 0.40]

# 고객 CDD 위험등급 분포 (금융정보분석원 가이드라인 참고)
RISK_LEVELS = [1, 2, 3, 4, 5]  # 1=LOW, 2=NORMAL, 3=MEDIUM, 4=HIGH, 5=CRITICAL
RISK_PROBS = [0.30, 0.40, 0.20, 0.08, 0.02]

# 거래 시작 기준일
BASE_DATETIME = datetime(2025, 1, 6, 9, 0, 0)  # 월요일 영업시작


def _make_index():
    """
    Branch-Account-Channel-거래 순서로 인덱스 생성 (1,000 rows).
    각 row에 거래 일시, 유형, 고객 위험등급 등 부가 정보를 부여.
    """
    records = []
    t = 0
    for a in range(1, N_ACCOUNTS + 1):
        for c in range(1, N_CHANNELS + 1):
            for m in range(N_TX):
                # 거래 일시: 5분 간격 + 영업시간(09~18) 기반
                tx_dt = BASE_DATETIME + timedelta(minutes=t * 5)
                tx_type = np.random.choice(TX_TYPES, p=TX_TYPE_PROBS)
                risk = int(np.random.choice(RISK_LEVELS, p=RISK_PROBS))

                counterparty = ""
                if tx_type == "TRANSFER":
                    counterparty = f"EXT_{np.random.randint(1000, 9999)}"

                records.append({
                    "timestamp": t,
                    "tx_datetime": tx_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "tx_hour": tx_dt.hour,
                    "branch_id": BRANCH_ID,
                    "account_id": f"ACC{a:02d}",
                    "channel_id": f"CH{c:01d}",
                    "tx_type": tx_type,
                    "customer_risk_level": risk,
                    "counterparty_id": counterparty,
                })
                t += 1
    return pd.DataFrame(records)


def make_base_log(scenario_id="S1"):
    """
    기본 정상 거래 로그 생성.
    거래 금액은 정상 범위(30~70만원) 내 정규분포.
    FDS 응답시간은 금융보안원 권고(30ms) 기준 정규분포.
    """
    idx = _make_index()
    n = len(idx)  # 1000

    idx["scenario_id"] = scenario_id
    idx["tx_amount"] = 50 + np.random.normal(0, 1.5, n)
    idx["response_time_ms"] = 30 + np.random.normal(0, 1.0, n)
    idx["processing_time_ms"] = 100 + np.random.normal(0, 3, n)
    idx["error_code"] = 0
    idx["fraud_flag"] = 0

    return idx.reset_index(drop=True)


# ================================================================
# 이상 주입 함수 (Anomaly Injection)
# ================================================================

def _account_mask(df, account_from=1, account_to=None):
    """특정 account 범위에 해당하는 row mask 반환"""
    account_nums = df["account_id"].str.extract(r"ACC(\d+)")[0].astype(int)
    if account_to is None:
        account_to = N_ACCOUNTS
    return (account_nums >= account_from) & (account_nums <= account_to)


def _channel_mask(df, channel_ids):
    """특정 channel 번호 리스트에 해당하는 row mask 반환"""
    return df["channel_id"].isin([f"CH{c}" for c in channel_ids])


def inject_spike(df, start=300, end=340, magnitude=20):
    """거래 금액 일시적 스파이크 주입 (특정 시간대 고액 거래 급증)"""
    df = df.copy()
    df.loc[start:end, "tx_amount"] += magnitude
    return df


def inject_amount_drift_from_account(df, account_from=3, slope=0.005):
    """
    특정 계좌 이후 tx_amount 점진 상승.
    자금세탁 패턴: 거래 금액을 점진적으로 높여가는 structuring 의심.
    """
    df = df.copy()
    mask = _account_mask(df, account_from=account_from)
    drift_idx = df.index[mask]
    drift_vals = np.arange(len(drift_idx)) * slope * 40
    df.loc[drift_idx, "tx_amount"] += drift_vals
    return df


def inject_processing_time_drift(df, account_from=3, slope=0.15):
    """
    특정 계좌 이후 processing_time_ms 점진 증가.
    시스템 성능 저하 패턴: 채널 서버 과부하 또는 DB 지연.
    """
    df = df.copy()
    mask = _account_mask(df, account_from=account_from)
    drift_idx = df.index[mask]
    drift_vals = np.arange(len(drift_idx)) * slope
    df.loc[drift_idx, "processing_time_ms"] += drift_vals
    return df


def inject_error_repeat(df, positions):
    """
    특정 위치에 반복 error_code 삽입.
    네트워크 장애/채널 서버 오류 패턴.
    """
    df = df.copy()
    for p in positions:
        if 0 <= p < len(df):
            df.loc[p, "error_code"] = 21
    return df


def inject_channel_dropout(df, channel_ids, account_from=2, account_to=3):
    """
    특정 channel + account 구간에서 response_time 신호 손실.
    채널 장애: FDS 응답 불능 상태.
    """
    df = df.copy()
    mask = _channel_mask(df, channel_ids) & _account_mask(df, account_from, account_to)
    df.loc[mask, "response_time_ms"] = 0
    return df


def inject_noise_burst(df, start=200, end=260, scale=8):
    """
    시장 이벤트에 의한 거래금액 변동성 burst 주입.
    금융 시장 급변 시 이체/결제 금액 변동 급증 패턴.
    """
    df = df.copy()
    noise = np.random.normal(0, scale, end - start + 1)
    df.loc[start:end, "tx_amount"] += noise
    return df


def inject_amount_high_accounts(df, account_from=2, account_to=5, offset=22):
    """
    특정 계좌 범위 전체에서 tx_amount 높은 수준 지속.
    고액 이상 거래 패턴: 특정 계좌군의 평균 거래금액 이상 상승.
    """
    df = df.copy()
    mask = _account_mask(df, account_from=account_from, account_to=account_to)
    df.loc[mask, "tx_amount"] += offset
    return df


# ================================================================
# 시나리오 빌드 (10개)
# ================================================================

def build_scenarios():
    """
    FDS 검증용 10개 시나리오를 생성한다.

    S1:  정상 거래 (baseline)
    S2:  거래금액 일시 스파이크 후 자가 회복
    S3:  거래금액 지속 상승 — 고액 이상거래 의심
    S4:  시스템 처리시간 점진 증가 — 채널 성능 저하
    S5:  반복 거래 에러 — 네트워크/채널 장애 의심
    S6:  채널 응답 손실 — FDS 응답 불능
    S7:  시장 변동성 burst 후 회복
    S8:  복합 이상 — 금액+처리시간+에러+이상거래 플래그
    S9:  거래금액 이상 감지 후 재검증 통과
    S10: 거래금액+처리시간 이상 후 회복 실패
    """
    scenarios = []

    # S1: 정상 거래 구간
    s1 = make_base_log("S1")
    scenarios.append(s1)

    # S2: ACC03에서 거래금액 순간 스파이크 후 자가 회복
    s2 = make_base_log("S2")
    s2 = inject_spike(s2, 400, 440, 18)
    scenarios.append(s2)

    # S3: ACC02 이후 거래금액 지속 상승 — 고액 이상거래 의심
    s3 = make_base_log("S3")
    s3 = inject_amount_high_accounts(s3, account_from=2, account_to=5, offset=22)
    scenarios.append(s3)

    # S4: ACC03 이후 처리시간 점진 증가 — 채널 성능 저하
    s4 = make_base_log("S4")
    s4 = inject_processing_time_drift(s4, account_from=3, slope=0.15)
    scenarios.append(s4)

    # S5: 반복 거래 에러 — 네트워크 장애 의심
    s5 = make_base_log("S5")
    s5 = inject_error_repeat(s5, [200, 280, 360, 440, 520])
    scenarios.append(s5)

    # S6: ACC02~ACC03 CH5에서 응답시간 손실 — FDS 응답 불능
    s6 = make_base_log("S6")
    s6 = inject_channel_dropout(s6, channel_ids=[5], account_from=2, account_to=3)
    scenarios.append(s6)

    # S7: ACC02에서 시장 변동성 burst 후 회복
    s7 = make_base_log("S7")
    s7 = inject_noise_burst(s7, 200, 295, 10)
    scenarios.append(s7)

    # S8: 복합 이상 — 금액 drift + 처리시간 + 에러 + fraud flag
    s8 = make_base_log("S8")
    s8 = inject_amount_drift_from_account(s8, account_from=2, slope=0.008)
    s8 = inject_processing_time_drift(s8, account_from=2, slope=0.12)
    s8 = inject_error_repeat(s8, [220, 260, 300, 340, 380])
    account2_5_mask = _account_mask(s8, account_from=2, account_to=5)
    s8.loc[account2_5_mask, "fraud_flag"] = 1
    scenarios.append(s8)

    # S9: 거래금액 이상 감지 → 재검증 통과
    s9 = make_base_log("S9")
    s9 = inject_spike(s9, 400, 510, 15)
    s9 = inject_error_repeat(s9, [420, 460])
    scenarios.append(s9)

    # S10: 거래금액+처리시간 이상 후 회복 실패 — 최종 FAIL
    s10 = make_base_log("S10")
    s10 = inject_amount_high_accounts(s10, account_from=2, account_to=5, offset=18)
    s10 = inject_processing_time_drift(s10, account_from=2, slope=0.10)
    s10 = inject_error_repeat(s10, [250, 330, 410, 490])
    scenarios.append(s10)

    return pd.concat(scenarios, ignore_index=True)


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(project_root, "data/raw"), exist_ok=True)

    df = build_scenarios()
    save_path = os.path.join(project_root, "data/raw/transaction_logs.csv")
    df.to_csv(save_path, index=False)

    print("=" * 60)
    print("  금융 거래 FDS 시뮬레이션 로그 생성 완료")
    print("=" * 60)
    print(f"\n파일: {save_path}")
    print(f"총 row 수: {len(df)}")
    print(f"시나리오 수: {df['scenario_id'].nunique()}")
    print(f"\n컬럼 ({len(df.columns)}개):")
    for col in df.columns:
        print(f"  - {col}")
    print(f"\n거래 유형 분포:")
    print(df["tx_type"].value_counts().to_string())
    print(f"\n고객 위험등급 분포:")
    print(df["customer_risk_level"].value_counts().sort_index().to_string())
    print(f"\n거래 일시 범위: {df['tx_datetime'].min()} ~ {df['tx_datetime'].max()}")


if __name__ == "__main__":
    main()
