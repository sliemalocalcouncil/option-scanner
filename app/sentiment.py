"""
Bull/Bear 종합 점수.

스코어 규약:
  - 모든 컴포넌트 점수는 -100 (강한 약세) ~ 0 (중립) ~ +100 (강한 강세)
  - None 컴포넌트는 평균에서 제외
  - 모든 입력은 None-safe

옵션 컴포넌트 (가중치 0.6):
  pc_volume    : Put/Call Volume Ratio (낮을수록 bullish)
  pc_oi        : Put/Call OI Ratio (낮을수록 bullish)
  iv_skew      : 25Δ Call IV - 25Δ Put IV (양수일수록 bullish)
  dw_oi        : Σ(call OI × Δ) - Σ(put OI × |Δ|)  (양수=bullish)
  dw_volume    : 위와 동일하나 day volume 기준

주식 컴포넌트 (가중치 0.4):
  ma_position  : SMA20/SMA50 대비 가격 위치
  rsi_zone     : RSI(14)
  macd_hist    : MACD 히스토그램 부호 + 강도
  momentum     : 최근 5일 수익률
"""
from __future__ import annotations

import math
from statistics import mean

import numpy as np
import pandas as pd

from .indicators import macd, rsi


# ---------- 유틸: 비율을 -100..+100 점수로 ----------
def _ratio_to_score(ratio: float, neutral: float = 1.0, fullbear: float = 2.0) -> float:
    """
    P/C 비율 변환.
    1.0 = 중립(0), 2.0 = -100, 0.5 = +100.
    """
    if ratio is None or ratio <= 0:
        return None
    # 로그 스케일이라야 0.5와 2.0이 대칭
    score = -100.0 * math.log(ratio / neutral) / math.log(fullbear / neutral)
    return max(-100.0, min(100.0, score))


def _clip(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ---------- 옵션 컴포넌트 ----------
def pc_volume_score(rows: list[dict]) -> tuple[float | None, dict]:
    call_v = sum((r["volume"] or 0) for r in rows if r["contract_type"] == "call")
    put_v = sum((r["volume"] or 0) for r in rows if r["contract_type"] == "put")
    if call_v == 0:
        return None, {"call_volume": call_v, "put_volume": put_v, "ratio": None}
    ratio = put_v / call_v
    return _ratio_to_score(ratio), {
        "call_volume": call_v, "put_volume": put_v, "ratio": ratio,
    }


def pc_oi_score(rows: list[dict]) -> tuple[float | None, dict]:
    call_oi = sum((r["open_interest"] or 0) for r in rows if r["contract_type"] == "call")
    put_oi = sum((r["open_interest"] or 0) for r in rows if r["contract_type"] == "put")
    if call_oi == 0:
        return None, {"call_oi": call_oi, "put_oi": put_oi, "ratio": None}
    ratio = put_oi / call_oi
    return _ratio_to_score(ratio), {
        "call_oi": call_oi, "put_oi": put_oi, "ratio": ratio,
    }


def iv_skew_score(rows: list[dict]) -> tuple[float | None, dict]:
    """25Δ 콜 IV - 25Δ 풋 IV. 25Δ에 가장 가까운 계약 사용."""
    calls = [r for r in rows if r["contract_type"] == "call"
             and r["delta"] is not None and r["iv"] is not None]
    puts = [r for r in rows if r["contract_type"] == "put"
            and r["delta"] is not None and r["iv"] is not None]
    if not calls or not puts:
        return None, {"call_iv_25d": None, "put_iv_25d": None, "skew": None}

    c25 = min(calls, key=lambda r: abs(abs(r["delta"]) - 0.25))
    p25 = min(puts, key=lambda r: abs(abs(r["delta"]) - 0.25))
    skew = c25["iv"] - p25["iv"]   # 양수: 콜 IV가 더 비싸다 = bullish

    # 보통 SPY/대형주는 -3% ~ -10% 사이 (풋이 비쌈). ±10%를 -100~+100로 매핑.
    score = _clip(skew / 0.10 * 100.0)
    return score, {
        "call_iv_25d": c25["iv"], "put_iv_25d": p25["iv"], "skew": skew,
        "call_strike": c25["strike"], "put_strike": p25["strike"],
    }


def _delta_weighted(rows: list[dict], field: str) -> tuple[float | None, dict]:
    call_w = sum(
        ((r[field] or 0) * r["delta"])
        for r in rows
        if r["contract_type"] == "call" and r["delta"] is not None
    )
    put_w = sum(
        ((r[field] or 0) * abs(r["delta"]))
        for r in rows
        if r["contract_type"] == "put" and r["delta"] is not None
    )
    net = call_w - put_w
    total = abs(call_w) + abs(put_w)
    if total == 0:
        return None, {"call": call_w, "put": put_w, "net": net}
    # 점수: net/total → -1 ~ +1 → -100 ~ +100
    return _clip(net / total * 100.0), {
        "call": call_w, "put": put_w, "net": net,
    }


def dw_oi_score(rows): return _delta_weighted(rows, "open_interest")
def dw_volume_score(rows): return _delta_weighted(rows, "volume")


def option_sentiment(rows: list[dict]) -> dict:
    """5개 컴포넌트 → 옵션 종합 점수."""
    pc_v, pc_v_d = pc_volume_score(rows)
    pc_o, pc_o_d = pc_oi_score(rows)
    skew, skew_d = iv_skew_score(rows)
    dwoi, dwoi_d = dw_oi_score(rows)
    dwv, dwv_d = dw_volume_score(rows)

    components = {
        "pc_volume": {"score": pc_v, **pc_v_d},
        "pc_oi": {"score": pc_o, **pc_o_d},
        "iv_skew": {"score": skew, **skew_d},
        "dw_oi": {"score": dwoi, **dwoi_d},
        "dw_volume": {"score": dwv, **dwv_d},
    }
    scores = [s for s in (pc_v, pc_o, skew, dwoi, dwv) if s is not None]
    overall = mean(scores) if scores else None
    return {"score": overall, "components": components}


# ---------- 주식 컴포넌트 ----------
def stock_sentiment(bars: list[dict]) -> dict:
    """일봉 리스트 → 주식 종합 점수."""
    if not bars or len(bars) < 30:
        return {"score": None, "components": {}}

    df = pd.DataFrame(bars).sort_values("t").reset_index(drop=True)
    close = df["c"].astype(float)
    last = float(close.iloc[-1])

    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None

    # MA position: last vs sma20·sma50
    ma_score: float | None = None
    if not math.isnan(sma20):
        # last/sma20 - 1 → ±5%면 ±100 가정
        s20 = _clip((last / sma20 - 1) / 0.05 * 100.0)
        if sma50 is not None and not math.isnan(sma50):
            s50 = _clip((last / sma50 - 1) / 0.10 * 100.0)
            ma_score = (s20 + s50) / 2
        else:
            ma_score = s20

    # RSI: 50이 중립, 70이상/30이하는 극단
    rsi_val = float(rsi(close).iloc[-1])
    rsi_zone = _clip((rsi_val - 50) / 20.0 * 100.0)

    # MACD histogram
    macd_line, signal, hist = macd(close)
    h = float(hist.iloc[-1])
    # 가격 대비 정규화: hist / last × 1000 (대충 ±100 범위)
    macd_score = _clip(h / max(last, 1e-9) * 1000.0)

    # Momentum: 5일 수익률
    if len(close) >= 6:
        ret5 = float(close.iloc[-1] / close.iloc[-6] - 1)
        # ±5%를 ±100으로
        momentum = _clip(ret5 / 0.05 * 100.0)
    else:
        momentum = None

    components = {
        "ma_position": {
            "score": ma_score, "last": last,
            "sma20": None if math.isnan(sma20) else sma20,
            "sma50": sma50,
        },
        "rsi_zone": {"score": rsi_zone, "rsi": rsi_val},
        "macd_hist": {"score": macd_score, "hist": h},
        "momentum_5d": {"score": momentum,
                        "ret_5d": (None if momentum is None
                                   else float(close.iloc[-1]/close.iloc[-6] - 1))},
    }
    scores = [c["score"] for c in components.values() if c["score"] is not None]
    overall = mean(scores) if scores else None
    return {"score": overall, "components": components}


# ---------- 종합 ----------
def label_from_score(s: float | None) -> str:
    if s is None: return "N/A"
    if s >= 40: return "STRONG BULL"
    if s >= 15: return "BULLISH"
    if s > -15: return "NEUTRAL"
    if s > -40: return "BEARISH"
    return "STRONG BEAR"


def combined_sentiment(
    option_rows: list[dict],
    stock_bars: list[dict],
    *,
    option_weight: float = 0.6,
    stock_weight: float = 0.4,
) -> dict:
    opt = option_sentiment(option_rows)
    stk = stock_sentiment(stock_bars)

    parts = []
    if opt["score"] is not None: parts.append((opt["score"], option_weight))
    if stk["score"] is not None: parts.append((stk["score"], stock_weight))
    if parts:
        wsum = sum(w for _, w in parts)
        overall = sum(s * w for s, w in parts) / wsum
    else:
        overall = None

    return {
        "overall_score": overall,
        "label": label_from_score(overall),
        "option": opt,
        "stock": stk,
        "weights": {"option": option_weight, "stock": stock_weight},
    }
