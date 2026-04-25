import pandas as pd


def load_logs(path="data/raw/transaction_logs.csv"):
    """
    원본 거래 로그 csv 로드
    """
    df = pd.read_csv(path)
    return df


def add_rolling_features(df):
    """
    이상 탐지에 쓸 rolling feature 추가
    scenario별로 따로 계산해야 함
    """
    result = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()

        # rolling mean / std
        g["tx_amount_roll_mean"] = g["tx_amount"].rolling(window=20, min_periods=1).mean()
        g["tx_amount_roll_std"] = g["tx_amount"].rolling(window=20, min_periods=1).std().fillna(0)

        g["response_time_roll_mean"] = g["response_time_ms"].rolling(window=20, min_periods=1).mean()
        g["processing_time_roll_mean"] = g["processing_time_ms"].rolling(window=20, min_periods=1).mean()

        # baseline 대비 차이
        g["tx_amount_diff"] = g["tx_amount"] - g["tx_amount_roll_mean"]
        g["processing_time_diff"] = g["processing_time_ms"] - g["processing_time_roll_mean"]

        result.append(g)

    out = pd.concat(result, ignore_index=True)
    return out


def preprocess_logs(path="data/raw/transaction_logs.csv"):
    """
    전체 전처리 파이프라인
    """
    df = load_logs(path)
    df = add_rolling_features(df)
    return df
