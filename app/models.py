from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, DateTime, BigInteger, Index, Date, JSON
)

from .db import Base


class OptionContract(Base):
    """[1] /v3/reference/options/contracts 결과 캐시"""
    __tablename__ = "option_contracts"

    ticker = Column(String, primary_key=True)            # O:AAPL250117C00200000
    underlying_ticker = Column(String, index=True, nullable=False)
    expiration_date = Column(Date, nullable=False)
    contract_type = Column(String, nullable=False)       # call / put
    strike_price = Column(Float, nullable=False)
    shares_per_contract = Column(Integer, default=100)
    primary_exchange = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_contract_ul_exp", "underlying_ticker", "expiration_date"),
    )


class OptionSnapshot(Base):
    """[2] /v3/snapshot/options/{UL} 결과 (15분 지연)"""
    __tablename__ = "option_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    underlying_ticker = Column(String, index=True, nullable=False)
    snapshot_at = Column(DateTime, default=datetime.utcnow, index=True)

    # nullable: Greeks/IV는 가끔 null로 옴 - 필수 방어
    iv = Column(Float, nullable=True)
    delta = Column(Float, nullable=True)
    gamma = Column(Float, nullable=True)
    theta = Column(Float, nullable=True)
    vega = Column(Float, nullable=True)

    open_interest = Column(Float, nullable=True)
    day_volume = Column(Float, nullable=True)
    day_close = Column(Float, nullable=True)
    underlying_price = Column(Float, nullable=True)

    # 원본 보존 (디버깅 / 추후 분석)
    raw = Column(JSON, nullable=True)


class OptionBar(Base):
    """[4] /v2/aggs/ticker/{O:..}/range/... (옵션 OHLCV)"""
    __tablename__ = "option_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    t = Column(BigInteger, index=True, nullable=False)   # ms epoch
    o = Column(Float, nullable=True)
    h = Column(Float, nullable=True)
    l = Column(Float, nullable=True)
    c = Column(Float, nullable=True)
    v = Column(Float, nullable=True)
    vw = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_bar_ticker_t", "ticker", "t", unique=True),
    )


class OptionSignal(Base):
    """[5] 15분 지연 신호"""
    __tablename__ = "option_signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    underlying_ticker = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    kind = Column(String, nullable=False)          # iv_spike / oi_jump / vol_rank ...
    score = Column(Float, nullable=True)
    note = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
