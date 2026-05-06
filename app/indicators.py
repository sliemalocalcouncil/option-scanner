"""순수 numpy/pandas 인디케이터. Polygon이 제공하지 않는 RSI/MACD/BB 직접 계산."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(close: pd.Series, period: int = 20, k: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def attach_indicators(bars: list[dict]) -> dict:
    """Polygon aggs 결과에 RSI/MACD/BB 컬럼 추가해 반환."""
    if not bars:
        return {"bars": [], "indicators": {}}
    df = pd.DataFrame(bars).rename(columns={"t": "t"}).sort_values("t")
    close = df["c"].astype(float)

    df["rsi14"] = rsi(close, 14)
    macd_line, signal_line, hist = macd(close)
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist
    up, mid, low = bollinger(close)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = up, mid, low

    # NaN -> None (JSON 직렬화 안전)
    df = df.replace({np.nan: None})
    return {
        "bars": df.to_dict(orient="records"),
        "indicators": {
            "rsi_period": 14,
            "macd": [12, 26, 9],
            "bollinger": [20, 2.0],
        },
    }
