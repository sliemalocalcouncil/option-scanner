from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import models
from .db import get_db
from .indicators import attach_indicators
from .polygon import Polygon, PolygonError
from .ranker import detect_signals, filter_chain, normalize, rank

router = APIRouter(prefix="/api", tags=["options"])
poly = Polygon()


@router.get("/health")
async def health():
    return {"ok": True}


# ---- [1] Contract Selector ----
@router.get("/contracts")
async def list_contracts(
    ul: str = Query(..., description="기초자산 티커 (예: AAPL)"),
    expiration_date: Optional[str] = None,
    contract_type: Optional[str] = Query(None, pattern="^(call|put)$"),
    strike_gte: Optional[float] = None,
    strike_lte: Optional[float] = None,
    limit: int = 250,
    db: Session = Depends(get_db),
):
    try:
        results = await poly.list_contracts(
            ul,
            expiration_date=expiration_date,
            contract_type=contract_type,
            strike_gte=strike_gte,
            strike_lte=strike_lte,
            expired=False,
            limit=limit,
        )
    except PolygonError as e:
        raise HTTPException(502, str(e))

    # DB 캐시
    for r in results:
        c = models.OptionContract(
            ticker=r["ticker"],
            underlying_ticker=r.get("underlying_ticker") or ul.upper(),
            expiration_date=date.fromisoformat(r["expiration_date"]),
            contract_type=r["contract_type"],
            strike_price=float(r["strike_price"]),
            shares_per_contract=int(r.get("shares_per_contract") or 100),
            primary_exchange=r.get("primary_exchange"),
        )
        db.merge(c)
    db.commit()

    return {"count": len(results), "results": results}


# ---- [2] + [3] Snapshot + Rank (한 번에) ----
@router.get("/chain")
async def get_chain(
    ul: str,
    expiration_date: Optional[str] = None,
    contract_type: Optional[str] = Query(None, pattern="^(call|put)$"),
    strike_gte: Optional[float] = None,
    strike_lte: Optional[float] = None,
    min_dte: Optional[int] = None,
    max_dte: Optional[int] = None,
    delta_min: Optional[float] = None,
    delta_max: Optional[float] = None,
    max_strike_distance_pct: Optional[float] = Query(
        None, description="현재가로부터 ±n%"
    ),
    min_open_interest: Optional[float] = None,
    min_volume: Optional[float] = None,
    limit: int = 250,
    db: Session = Depends(get_db),
):
    try:
        raw = await poly.snapshot_chain(
            ul,
            expiration_date=expiration_date,
            contract_type=contract_type,
            strike_gte=strike_gte,
            strike_lte=strike_lte,
            limit=limit,
        )
    except PolygonError as e:
        raise HTTPException(502, str(e))

    # 평탄화 + 랭킹
    rows = [normalize(x) for x in raw]
    filtered = filter_chain(
        rows,
        min_dte=min_dte,
        max_dte=max_dte,
        delta_min=delta_min,
        delta_max=delta_max,
        max_strike_distance_pct=max_strike_distance_pct,
        contract_type=contract_type,
        min_open_interest=min_open_interest,
        min_volume=min_volume,
    )
    ranked = rank(filtered)

    # 스냅샷 저장 (감사/분석용 - 모든 행 저장은 비싸니 상위 50개만)
    for r in ranked[:50]:
        snap = models.OptionSnapshot(
            ticker=r["ticker"],
            underlying_ticker=ul.upper(),
            iv=r["iv"], delta=r["delta"], gamma=r["gamma"],
            theta=r["theta"], vega=r["vega"],
            open_interest=r["open_interest"],
            day_volume=r["volume"],
            day_close=r["day_close"],
            underlying_price=r["underlying_price"],
            raw=None,  # raw 통째 저장은 비활성, 필요시 r 자체 넣어도 됨
        )
        db.add(snap)
    db.commit()

    # 신호 생성
    signals = detect_signals(ranked)
    for s in signals:
        db.add(models.OptionSignal(
            ticker=s["ticker"],
            underlying_ticker=ul.upper(),
            kind=s["kind"], score=s["score"],
            note=s["note"], payload=s["payload"],
        ))
    db.commit()

    underlying_price = next(
        (r["underlying_price"] for r in ranked if r["underlying_price"]), None
    )

    return {
        "underlying": ul.upper(),
        "underlying_price": underlying_price,
        "delayed_minutes": 15,
        "count": len(ranked),
        "results": ranked,
        "signals": signals,
    }


# ---- [4] Option OHLCV ----
@router.get("/bars")
async def option_bars(
    ticker: str = Query(..., description="옵션 티커. 예: O:AAPL250117C00200000"),
    multiplier: int = 1,
    timespan: str = Query("day", pattern="^(minute|hour|day|week)$"),
    days: int = Query(120, ge=1, le=730),
    db: Session = Depends(get_db),
):
    to = date.today()
    from_ = to - timedelta(days=days)
    try:
        bars = await poly.option_aggs(
            ticker,
            multiplier=multiplier,
            timespan=timespan,
            from_=from_.isoformat(),
            to=to.isoformat(),
        )
    except PolygonError as e:
        raise HTTPException(502, str(e))

    # DB 저장 (중복은 unique 인덱스로 거름)
    for b in bars:
        try:
            db.add(models.OptionBar(
                ticker=ticker, t=b["t"],
                o=b.get("o"), h=b.get("h"), l=b.get("l"),
                c=b.get("c"), v=b.get("v"), vw=b.get("vw"),
            ))
            db.commit()
        except Exception:
            db.rollback()

    return attach_indicators(bars) | {"ticker": ticker, "delayed_minutes": 15}


# ---- 기초주식 OHLCV (간단 버전) ----
@router.get("/stock_bars")
async def stock_bars(
    ticker: str,
    multiplier: int = 1,
    timespan: str = "day",
    days: int = 120,
):
    to = date.today()
    from_ = to - timedelta(days=days)
    try:
        bars = await poly.option_aggs(  # /v2/aggs/ticker 는 주식에도 동일하게 작동
            ticker.upper(),
            multiplier=multiplier,
            timespan=timespan,
            from_=from_.isoformat(),
            to=to.isoformat(),
        )
    except PolygonError as e:
        raise HTTPException(502, str(e))
    return attach_indicators(bars) | {"ticker": ticker.upper()}


# ---- [5] 신호 조회 ----
@router.get("/signals")
async def get_signals(
    ul: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(models.OptionSignal).order_by(models.OptionSignal.created_at.desc())
    if ul:
        q = q.filter(models.OptionSignal.underlying_ticker == ul.upper())
    rows = q.limit(limit).all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "underlying": r.underlying_ticker,
            "created_at": r.created_at.isoformat(),
            "kind": r.kind,
            "score": r.score,
            "note": r.note,
        }
        for r in rows
    ]
