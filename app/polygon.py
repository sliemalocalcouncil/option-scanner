"""
Polygon Options Starter 호환 클라이언트.

핵심 원칙:
  - greeks / iv / last_quote / last_trade 필드는 항상 nullable 처리.
  - 15분 지연 데이터를 전제로 한다 (실시간 플로우/sweep 탐지 안 함).
"""
from __future__ import annotations

from typing import Any
import httpx

from .config import settings


class PolygonError(RuntimeError):
    pass


class Polygon:
    def __init__(self, api_key: str | None = None, base: str | None = None):
        self.api_key = api_key or settings.POLYGON_API_KEY
        self.base = (base or settings.POLYGON_BASE).rstrip("/")
        if not self.api_key:
            # 키가 없어도 인스턴스는 만들 수 있게 - 호출 시 에러
            pass

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.api_key:
            raise PolygonError("POLYGON_API_KEY 가 설정되지 않았습니다.")
        params = dict(params or {})
        params["apiKey"] = self.api_key
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            if r.status_code >= 400:
                raise PolygonError(f"Polygon {r.status_code}: {r.text[:300]}")
            return r.json()

    # ---------- [1] Contract Selector ----------
    async def list_contracts(
        self,
        underlying: str,
        *,
        expiration_date: str | None = None,
        contract_type: str | None = None,        # call / put
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        expired: bool = False,
        limit: int = 250,
    ) -> list[dict]:
        params = {
            "underlying_ticker": underlying.upper(),
            "expired": str(expired).lower(),
            "limit": limit,
            "order": "asc",
            "sort": "expiration_date",
        }
        if expiration_date:
            params["expiration_date"] = expiration_date
        if contract_type:
            params["contract_type"] = contract_type
        if strike_gte is not None:
            params["strike_price.gte"] = strike_gte
        if strike_lte is not None:
            params["strike_price.lte"] = strike_lte

        data = await self._get("/v3/reference/options/contracts", params)
        return data.get("results") or []

    # ---------- [2] Option Chain Snapshot ----------
    async def snapshot_chain(
        self,
        underlying: str,
        *,
        expiration_date: str | None = None,
        contract_type: str | None = None,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 250,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if expiration_date:
            params["expiration_date"] = expiration_date
        if contract_type:
            params["contract_type"] = contract_type
        if strike_gte is not None:
            params["strike_price.gte"] = strike_gte
        if strike_lte is not None:
            params["strike_price.lte"] = strike_lte

        data = await self._get(
            f"/v3/snapshot/options/{underlying.upper()}", params
        )
        return data.get("results") or []

    # ---------- [4] Option OHLCV ----------
    async def option_aggs(
        self,
        option_ticker: str,
        *,
        multiplier: int = 1,
        timespan: str = "day",            # minute / hour / day
        from_: str = "2024-01-01",
        to: str = "2025-12-31",
        adjusted: bool = True,
        limit: int = 5000,
    ) -> list[dict]:
        path = (
            f"/v2/aggs/ticker/{option_ticker}/range/"
            f"{multiplier}/{timespan}/{from_}/{to}"
        )
        data = await self._get(
            path, {"adjusted": str(adjusted).lower(), "limit": limit, "sort": "asc"}
        )
        return data.get("results") or []


# ---------- 안전한 파싱 헬퍼 (greeks/iv 등 None 방어) ----------
def safe_get(d: dict | None, *path, default=None):
    cur: Any = d
    for p in path:
        if cur is None or not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default
