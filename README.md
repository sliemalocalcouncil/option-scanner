# Options Scanner — Polygon Starter (15m delayed)

폴리곤 **Options Starter** 플랜에 맞춘 옵션 스캐너 웹앱.
실시간 플로우/sweep/tick 매수·매도 판별 같이 라이센스 위반 가능 기능은 포함하지 않음.

- 데이터: `/v3/reference/options/contracts`, `/v3/snapshot/options/{UL}`, `/v2/aggs/ticker/{O:..}/range/...`
- 인디케이터(RSI / MACD / Bollinger)는 Polygon에서 제공하지 않으므로 직접 계산
- `greeks`, `implied_volatility`, `last_quote`, `last_trade`는 항상 `null` 처리 (필수 방어)
- 모든 응답에 `delayed_minutes: 15` 표기

## 구조

```
app/
  main.py            # FastAPI 진입점, /static 마운트
  config.py          # POLYGON_API_KEY, DATABASE_URL
  db.py / models.py  # SQLAlchemy: option_contracts/snapshots/bars/signals
  polygon.py         # Polygon API 래퍼 + safe_get
  ranker.py          # [3] 필터 + Volume/OI/IV 랭크 + 신호 검출
  indicators.py      # RSI / MACD / Bollinger
  routes.py          # /api/contracts /chain /bars /stock_bars /signals
static/              # index.html / style.css / app.js (Chart.js)
render.yaml          # Render 블루프린트
```

## 로컬 실행

```bash
cp .env.example .env       # POLYGON_API_KEY 채우기
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://localhost:8000  → 프론트엔드
# http://localhost:8000/docs → Swagger
```

`.env`에 `DATABASE_URL`이 비어 있으면 `sqlite:///./local.db`로 자동 폴백.

## Render 배포 (블루프린트)

1. 이 저장소를 GitHub에 push
2. Render 대시보드 → **New +** → **Blueprint** → 저장소 선택
3. `render.yaml`이 자동 감지되며 다음을 생성
   - **PostgreSQL DB** `options-scanner-db`
   - **Web service** `options-scanner` (FastAPI)
4. 웹서비스 환경변수에서 **`POLYGON_API_KEY`** 만 직접 입력
5. Deploy → 도메인에 접속해 UL 입력하고 SCAN

`DATABASE_URL`은 블루프린트가 자동 주입한다.

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/contracts?ul=AAPL&...` | 계약 검색 (만기/타입/스트라이크 범위) |
| GET | `/api/chain?ul=AAPL&...`     | 스냅샷 + 필터 + 랭킹 + 신호 |
| GET | `/api/bars?ticker=O:...`     | 옵션 OHLCV + RSI/MACD/BB |
| GET | `/api/stock_bars?ticker=AAPL`| 기초주식 OHLCV |
| GET | `/api/signals?ul=AAPL`       | DB에 누적된 지연 신호 |

`/api/chain` 주요 파라미터:

```
ul, expiration_date, contract_type=call|put,
strike_gte, strike_lte,
min_dte, max_dte, delta_min, delta_max,
max_strike_distance_pct,        # 현재가 대비 ±n%
min_open_interest, min_volume,
limit (default 250)
```

## 디스클레이머

- 이 도구는 **분석·교육 목적**이며 매매 권유가 아님
- 모든 데이터는 **15분 지연**, 즉시 체결가 반영을 의미하지 않음
- Polygon Options Starter 라이센스 한도 안에서만 호출
