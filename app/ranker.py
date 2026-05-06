"""
[3] Option Contract Ranker.
스냅샷 결과 리스트를 받아 점수화/필터링한다.

입력 한 건 예시 (Polygon /v3/snapshot/options/{UL}.results[i]):
{
  "details": {"ticker": "O:...", "contract_type": "call",
              "strike_price": 200, "expiration_date": "2025-01-17"},
  "greeks": {"delta": 0.42, ...} | None,
  "implied_volatility": 0.31 | None,
  "open_interest": 1234 | None,
  "day": {"volume": 500, "close": 1.23, ...} | None,
  "last_quote": {...} | None,
  "last_trade": {...} | None,
  "underlying_asset": {"price": 198.5, ...} | None,
}
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .polygon import safe_get


def _dte(exp: str | None) -> int | None:
    if not exp:
        return None
    try:
        d = datetime.strptime(exp, "%Y-%m-%d").date()
        return (d - date.today()).days
    except ValueError:
        return None


def normalize(item: dict) -> dict:
    """스냅샷 한 건을 평탄화 + None 방어."""
    details = item.get("details") or {}
    greeks = item.get("greeks") or {}
    day = item.get("day") or {}
    ul = item.get("underlying_asset") or {}

    return {
        "ticker": details.get("ticker"),
        "contract_type": details.get("contract_type"),
        "strike": details.get("strike_price"),
        "expiration_date": details.get("expiration_date"),
        "dte": _dte(details.get("expiration_date")),

        "iv": item.get("implied_volatility"),       # nullable
        "delta": greeks.get("delta"),               # nullable
        "gamma": greeks.get("gamma"),
        "theta": greeks.get("theta"),
        "vega": greeks.get("vega"),

        "open_interest": item.get("open_interest"),
        "volume": day.get("volume"),
        "day_close": day.get("close"),
        "underlying_price": ul.get("price"),

        "last_quote_bid": safe_get(item, "last_quote", "bid"),
        "last_quote_ask": safe_get(item, "last_quote", "ask"),
        "last_trade_price": safe_get(item, "last_trade", "price"),
    }


def filter_chain(
    rows: list[dict],
    *,
    min_dte: int | None = None,
    max_dte: int | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    max_strike_distance_pct: float | None = None,
    contract_type: str | None = None,
    min_open_interest: float | None = None,
    min_volume: float | None = None,
) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        if contract_type and r["contract_type"] != contract_type:
            continue
        if min_dte is not None and (r["dte"] is None or r["dte"] < min_dte):
            continue
        if max_dte is not None and (r["dte"] is None or r["dte"] > max_dte):
            continue
        if delta_min is not None and (r["delta"] is None or r["delta"] < delta_min):
            continue
        if delta_max is not None and (r["delta"] is None or r["delta"] > delta_max):
            continue
        if min_open_interest is not None and (r["open_interest"] or 0) < min_open_interest:
            continue
        if min_volume is not None and (r["volume"] or 0) < min_volume:
            continue
        if max_strike_distance_pct is not None:
            ul, k = r["underlying_price"], r["strike"]
            if ul and k:
                dist = abs(k - ul) / ul * 100.0
                if dist > max_strike_distance_pct:
                    continue
        out.append(r)
    return out


def _rank(values: list[float | None], reverse: bool = True) -> list[float | None]:
    """None 은 None으로 두고, 나머지를 0~100 백분위로."""
    idx = [(i, v) for i, v in enumerate(values) if v is not None]
    if not idx:
        return [None] * len(values)
    idx.sort(key=lambda x: x[1], reverse=reverse)
    n = len(idx)
    pct: dict[int, float] = {}
    for rank_i, (orig_i, _) in enumerate(idx):
        # 1등 -> 100, 꼴등 -> 0
        pct[orig_i] = 100.0 * (n - 1 - rank_i) / max(n - 1, 1)
    return [pct.get(i) for i in range(len(values))]


def rank(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    vol_rank = _rank([r["volume"] for r in rows], reverse=True)
    oi_rank = _rank([r["open_interest"] for r in rows], reverse=True)
    iv_rank = _rank([r["iv"] for r in rows], reverse=True)

    enriched: list[dict] = []
    for r, vr, oir, ivr in zip(rows, vol_rank, oi_rank, iv_rank):
        # 종합 점수 (모두 None이면 점수도 None)
        components = [c for c in (vr, oir, ivr) if c is not None]
        score = sum(components) / len(components) if components else None
        enriched.append({
            **r,
            "rank_volume": vr,
            "rank_oi": oir,
            "rank_iv": ivr,
            "score": score,
        })
    enriched.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    return enriched


def detect_signals(ranked: list[dict]) -> list[dict[str, Any]]:
    """간단한 15분 지연 신호 후보 (실시간 플로우/sweep 아님)."""
    signals: list[dict[str, Any]] = []
    for r in ranked:
        # 1) 거래량/OI 동시 상위 + IV 상위
        if (
            (r["rank_volume"] or 0) >= 90
            and (r["rank_oi"] or 0) >= 70
            and (r["rank_iv"] or 0) >= 70
        ):
            signals.append({
                "ticker": r["ticker"],
                "kind": "vol_oi_iv_top",
                "score": r["score"],
                "note": "Volume·OI·IV 동시 상위 (지연 스냅샷 기준)",
                "payload": r,
            })
        # 2) 외가격 강세 후보 (delta 0.15~0.35, 거래량 상위)
        elif (
            r["delta"] is not None
            and 0.15 <= abs(r["delta"]) <= 0.35
            and (r["rank_volume"] or 0) >= 85
        ):
            signals.append({
                "ticker": r["ticker"],
                "kind": "otm_volume_pop",
                "score": r["score"],
                "note": "OTM 후보, 거래량 급증 (지연)",
                "payload": r,
            })
    return signals
