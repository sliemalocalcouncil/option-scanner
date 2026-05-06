from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import models
from .db import get_db
from .indicators import attach_indicators
from .polygon import Polygon, PolygonError
from .ranker import detect_signals, filter_chain, normalize, rank
from .sentiment import combined_sentiment
from .uoa import detect_uoa

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


# ---- Bull/Bear Sentiment (옵션 + 주식 종합) ----
@router.get("/sentiment")
async def get_sentiment(
    ul: str,
    expiration_date: Optional[str] = None,
    max_strike_distance_pct: float = Query(15.0, description="±n% 이내 계약만 포함"),
    days: int = Query(120, description="주식 일봉 lookback"),
):
    """단일 UL의 Bull/Bear 종합 점수."""
    try:
        # 옵션 스냅샷 (한 번만 호출)
        raw = await poly.snapshot_chain(
            ul, expiration_date=expiration_date, limit=250,
        )
        # 주식 일봉
        to = date.today()
        from_ = to - timedelta(days=days)
        stock_bars = await poly.option_aggs(
            ul.upper(), multiplier=1, timespan="day",
            from_=from_.isoformat(), to=to.isoformat(),
        )
    except PolygonError as e:
        raise HTTPException(502, str(e))

    rows = [normalize(x) for x in raw]
    rows = filter_chain(rows, max_strike_distance_pct=max_strike_distance_pct)

    result = combined_sentiment(rows, stock_bars)
    return {
        "underlying": ul.upper(),
        "delayed_minutes": 15,
        "n_contracts_used": len(rows),
        **result,
    }


# ---- Unusual Option Activity ----
@router.get("/uoa")
async def get_uoa(
    ul: str,
    min_vol_oi: float = Query(1.0, description="Vol/OI 비율 하한"),
    min_volume: float = Query(50.0),
    history_days: int = Query(20, ge=5, le=60),
    top_n_for_zscore: int = Query(15, ge=1, le=50,
        description="z-score 계산 대상 (거래량 상위 N)"),
    db: Session = Depends(get_db),
):
    """단일 UL의 UOA 후보 탐지."""
    try:
        raw = await poly.snapshot_chain(ul, limit=250)
    except PolygonError as e:
        raise HTTPException(502, str(e))

    rows = [normalize(x) for x in raw]
    results = await detect_uoa(
        rows, poly, db,
        min_vol_oi=min_vol_oi,
        min_volume=min_volume,
        history_days=history_days,
        top_n_for_zscore=top_n_for_zscore,
    )

    # 신호 테이블에도 저장 (UI에서 시계열로 보고 싶을 때 활용)
    for r in results[:20]:
        db.add(models.OptionSignal(
            ticker=r["ticker"],
            underlying_ticker=ul.upper(),
            kind="uoa",
            score=r["uoa_score"],
            note=f"VolOI={r['vol_oi_ratio']:.2f} z={r['z_score']}",
            payload={k: r[k] for k in ("vol_oi_ratio", "z_score", "oi_jump",
                                       "volume", "open_interest", "delta", "iv")},
        ))
    db.commit()

    return {
        "underlying": ul.upper(),
        "delayed_minutes": 15,
        "count": len(results),
        "results": results,
    }


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
