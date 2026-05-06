"""
Unusual Option Activity 탐지.

세 가지 시그널을 결합한다:
  1) Vol/OI ratio    - 오늘 거래량이 누적 OI 대비 얼마나 큰가
  2) Volume z-score  - 과거 N일 거래량 대비 오늘 거래량의 통계적 이상치
  3) OI Jump         - DB에 누적된 어제 스냅샷 대비 OI 증가율

Polygon Starter 한도 고려:
  - z-score는 옵션 aggs 호출이 필요 → 상위 N개에 대해서만 계산
  - 일별 집계로만 동작 (tick 단위 X)
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

from sqlalchemy.orm import Session

from . import models
from .polygon import Polygon


def vol_oi_ratio(row: dict) -> float | None:
    v, oi = row.get("volume"), row.get("open_interest")
    if v is None or oi is None or oi <= 0:
        return None
    return v / oi


async def _fetch_volume_history(
    poly: Polygon, ticker: str, days: int = 20
) -> list[float]:
    """옵션 ticker의 최근 N 영업일 거래량."""
    to = date.today()
    from_ = to - timedelta(days=days * 2 + 7)  # 주말/휴장 여유
    try:
        bars = await poly.option_aggs(
            ticker, multiplier=1, timespan="day",
            from_=from_.isoformat(), to=to.isoformat(),
        )
    except Exception:
        return []
    return [float(b["v"]) for b in bars[-days:] if b.get("v") is not None]


def _z_score(today_vol: float | None, history: list[float]) -> float | None:
    if today_vol is None or len(history) < 5:
        return None
    mu = mean(history)
    sd = pstdev(history) or 1e-9
    return (today_vol - mu) / sd


def _oi_jump(db: Session, ticker: str, today_oi: float | None) -> dict:
    """어제 DB 스냅샷 대비 OI 증가율."""
    if today_oi is None:
        return {"yesterday_oi": None, "delta": None, "pct": None}
    yesterday = datetime.utcnow() - timedelta(hours=20)
    prev = (
        db.query(models.OptionSnapshot)
        .filter(models.OptionSnapshot.ticker == ticker)
        .filter(models.OptionSnapshot.snapshot_at <= yesterday)
        .order_by(models.OptionSnapshot.snapshot_at.desc())
        .first()
    )
    if not prev or prev.open_interest is None:
        return {"yesterday_oi": None, "delta": None, "pct": None}
    delta = today_oi - prev.open_interest
    pct = (delta / prev.open_interest * 100.0) if prev.open_interest > 0 else None
    return {
        "yesterday_oi": prev.open_interest,
        "delta": delta,
        "pct": pct,
    }


def _uoa_score(vol_oi: float | None, z: float | None, oi_pct: float | None) -> float:
    """0~100 종합 점수."""
    parts: list[float] = []
    # Vol/OI: 1.0=50점, 2.0=80점, 3.0=100점 (선형)
    if vol_oi is not None:
        parts.append(max(0.0, min(100.0, vol_oi * 33.0)))
    # z-score: 2σ=60점, 3σ=85점, 4σ=100점
    if z is not None:
        parts.append(max(0.0, min(100.0, z * 25.0 + 10.0)))
    # OI 증가율: 50%=50점, 100%=85점, 200%=100점
    if oi_pct is not None:
        parts.append(max(0.0, min(100.0, oi_pct / 2.0)))
    return mean(parts) if parts else 0.0


async def detect_uoa(
    rows: list[dict],
    poly: Polygon,
    db: Session,
    *,
    top_n_for_zscore: int = 15,
    history_days: int = 20,
    min_vol_oi: float = 1.0,
    min_volume: float = 50.0,
) -> list[dict]:
    """
    rows: ranker.normalize() 거친 옵션 행 목록.
    1차로 Vol/OI ≥ min_vol_oi & volume ≥ min_volume 필터 → 후보 선정
    2차로 후보 중 거래량 상위 top_n_for_zscore 개에 대해서만 aggs 호출 (API 절약)
    """
    # 1) 1차 필터
    cands: list[dict] = []
    for r in rows:
        if (r["volume"] or 0) < min_volume:
            continue
        ratio = vol_oi_ratio(r)
        if ratio is None or ratio < min_vol_oi:
            continue
        cands.append({**r, "vol_oi_ratio": ratio})

    if not cands:
        return []

    # 2) 거래량 상위 top_n에 대해서만 z-score 호출
    cands.sort(key=lambda x: x["volume"] or 0, reverse=True)
    top_for_z = cands[:top_n_for_zscore]
    others = cands[top_n_for_zscore:]

    histories = await asyncio.gather(
        *[_fetch_volume_history(poly, r["ticker"], history_days) for r in top_for_z],
        return_exceptions=True,
    )
    z_map: dict[str, float | None] = {}
    for r, h in zip(top_for_z, histories):
        if isinstance(h, Exception):
            z_map[r["ticker"]] = None
        else:
            z_map[r["ticker"]] = _z_score(r["volume"], h)

    # 3) OI Jump (DB 조회는 빠르므로 모든 후보에 대해)
    enriched: list[dict] = []
    for r in cands:
        z = z_map.get(r["ticker"])
        oi = _oi_jump(db, r["ticker"], r["open_interest"])
        score = _uoa_score(r["vol_oi_ratio"], z, oi["pct"])
        enriched.append({
            **r,
            "z_score": z,
            "oi_jump": oi,
            "uoa_score": score,
        })

    enriched.sort(key=lambda x: x["uoa_score"], reverse=True)
    return enriched
