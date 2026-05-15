from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import json
import re
import uuid
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# MongoDB
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# Emergent LLM
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- Models ----------
class WatchlistStock(BaseModel):
    ticker: str
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AddStockRequest(BaseModel):
    ticker: str


class StockQuote(BaseModel):
    ticker: str
    name: Optional[str] = None
    currency: str = "USD"
    price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[int] = None
    price_mxn: Optional[float] = None
    exchange: Optional[str] = None
    sparkline: List[float] = []


class PredictionResponse(BaseModel):
    ticker: str
    prediction_price: Optional[float] = None
    prediction_change_percent: Optional[float] = None
    direction: str
    confidence: str
    rationale: str
    news: List[dict] = []
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AddLotRequest(BaseModel):
    ticker: str
    qty: float
    buy_price_usd: float
    buy_fx_rate: Optional[float] = None  # USD/MXN at purchase time
    buy_date: Optional[str] = None       # YYYY-MM-DD


class SetTargetRequest(BaseModel):
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None


DEFAULT_TICKERS = [
    "INTC", "SMCI", "VIST", "DELL", "QCOM", "NTR", "MELI",
    "BABA", "TQQQ", "NVDA", "WDC", "SLV",
]

# ---------- Helpers ----------
_exchange_cache = {"rate": None, "ts": None}


async def get_usd_mxn_rate() -> float:
    """Cache USD/MXN rate for 10 minutes."""
    now = datetime.now(timezone.utc)
    if _exchange_cache["rate"] and _exchange_cache["ts"] and (now - _exchange_cache["ts"]).total_seconds() < 600:
        return _exchange_cache["rate"]

    def fetch():
        # Primary: frankfurter.dev (no key, reliable)
        try:
            r = requests.get("https://api.frankfurter.dev/v1/latest", params={"base": "USD", "symbols": "MXN"}, timeout=8)
            if r.ok:
                data = r.json()
                rate = data.get("rates", {}).get("MXN")
                if rate:
                    return float(rate)
        except Exception as e:
            logger.warning(f"frankfurter failed: {e}")
        # Fallback: open.er-api.com
        try:
            r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8)
            if r.ok:
                data = r.json()
                rate = data.get("rates", {}).get("MXN")
                if rate:
                    return float(rate)
        except Exception as e:
            logger.warning(f"open.er-api failed: {e}")
        return 17.0  # last-resort fallback

    rate = await asyncio.to_thread(fetch)
    _exchange_cache["rate"] = rate
    _exchange_cache["ts"] = now
    return rate


def _fetch_quote_sync(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.fast_info
        info = dict(info) if info else {}
    except Exception:
        info = {}

    hist = t.history(period="1mo", interval="1d", auto_adjust=False)
    price = open_p = high = low = prev_close = None
    volume = None
    sparkline: List[float] = []
    if hist is not None and not hist.empty:
        last = hist.iloc[-1]
        price = float(last["Close"])
        open_p = float(last["Open"])
        high = float(last["High"])
        low = float(last["Low"])
        volume = int(last["Volume"]) if not (last["Volume"] is None) else None
        if len(hist) >= 2:
            prev_close = float(hist.iloc[-2]["Close"])
        else:
            prev_close = float(info.get("previous_close") or info.get("previousClose") or open_p)
        sparkline = [round(float(v), 2) for v in hist["Close"].tolist()]

    if price is None:
        # fallback to fast_info
        price = info.get("last_price") or info.get("lastPrice")
        open_p = info.get("open")
        high = info.get("day_high") or info.get("dayHigh")
        low = info.get("day_low") or info.get("dayLow")
        prev_close = info.get("previous_close") or info.get("previousClose")

    name = None
    exchange = None
    try:
        meta = t.get_info() if hasattr(t, "get_info") else t.info
        name = meta.get("shortName") or meta.get("longName")
        exchange = meta.get("exchange") or meta.get("fullExchangeName")
    except Exception:
        pass

    change = None
    change_percent = None
    if price is not None and prev_close:
        change = price - prev_close
        if prev_close:
            change_percent = (change / prev_close) * 100

    return {
        "ticker": ticker.upper(),
        "name": name,
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "open": open_p,
        "high": high,
        "low": low,
        "previous_close": prev_close,
        "volume": volume,
        "exchange": exchange,
        "sparkline": sparkline,
    }


async def fetch_quote(ticker: str, mxn_rate: float) -> StockQuote:
    try:
        data = await asyncio.to_thread(_fetch_quote_sync, ticker)
    except Exception as e:
        logger.error(f"quote fetch failed {ticker}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch {ticker}")
    if data["price"] is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker {ticker}")
    data["price_mxn"] = round(data["price"] * mxn_rate, 2) if data["price"] else None
    return StockQuote(**data)


def _fetch_history_sync(ticker: str) -> List[dict]:
    t = yf.Ticker(ticker)
    hist = t.history(period="1mo", interval="1d", auto_adjust=False)
    rows: List[dict] = []
    if hist is None or hist.empty:
        return rows
    for idx, r in hist.iterrows():
        rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 2),
            "high": round(float(r["High"]), 2),
            "low": round(float(r["Low"]), 2),
            "close": round(float(r["Close"]), 2),
            "volume": int(r["Volume"]) if r["Volume"] is not None else 0,
        })
    return rows


async def ensure_default_watchlist():
    count = await db.watchlist.count_documents({})
    if count == 0:
        docs = [{"ticker": t, "added_at": datetime.now(timezone.utc).isoformat()} for t in DEFAULT_TICKERS]
        await db.watchlist.insert_many(docs)


# ---------- Routes ----------
@api_router.get("/")
async def root():
    return {"message": "Stock Tracker API"}


@api_router.get("/exchange-rate")
async def exchange_rate():
    rate = await get_usd_mxn_rate()
    return {"base": "USD", "target": "MXN", "rate": rate, "fetched_at": datetime.now(timezone.utc).isoformat()}


@api_router.get("/watchlist")
async def get_watchlist():
    await ensure_default_watchlist()
    items = await db.watchlist.find({}, {"_id": 0}).sort("added_at", 1).to_list(500)
    return {"tickers": [it["ticker"] for it in items]}


@api_router.post("/watchlist")
async def add_to_watchlist(req: AddStockRequest):
    ticker = req.ticker.strip().upper()
    if not ticker or not re.match(r"^[A-Z0-9.\-]{1,10}$", ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    # Validate ticker exists
    try:
        rate = await get_usd_mxn_rate()
        await fetch_quote(ticker, rate)
    except HTTPException as e:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    existing = await db.watchlist.find_one({"ticker": ticker})
    if existing:
        return {"ticker": ticker, "status": "exists"}
    await db.watchlist.insert_one({"ticker": ticker, "added_at": datetime.now(timezone.utc).isoformat()})
    return {"ticker": ticker, "status": "added"}


@api_router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str):
    ticker = ticker.strip().upper()
    res = await db.watchlist.delete_one({"ticker": ticker})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"ticker": ticker, "status": "removed"}


@api_router.get("/quotes")
async def quotes(tickers: Optional[str] = None):
    await ensure_default_watchlist()
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        items = await db.watchlist.find({}, {"_id": 0}).sort("added_at", 1).to_list(500)
        ticker_list = [it["ticker"] for it in items]

    mxn_rate = await get_usd_mxn_rate()

    async def safe(t):
        try:
            return await fetch_quote(t, mxn_rate)
        except Exception as e:
            logger.warning(f"Skip {t}: {e}")
            return None

    results = await asyncio.gather(*[safe(t) for t in ticker_list])
    return {
        "mxn_rate": mxn_rate,
        "quotes": [r.model_dump() for r in results if r is not None],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@api_router.get("/quote/{ticker}")
async def single_quote(ticker: str):
    mxn_rate = await get_usd_mxn_rate()
    q = await fetch_quote(ticker.upper(), mxn_rate)
    return {"mxn_rate": mxn_rate, "quote": q.model_dump()}


@api_router.get("/history/{ticker}")
async def history(ticker: str):
    rows = await asyncio.to_thread(_fetch_history_sync, ticker.upper())
    if not rows:
        raise HTTPException(status_code=404, detail="No history available")
    return {"ticker": ticker.upper(), "history": rows}


@api_router.post("/predict/{ticker}")
async def predict(ticker: str, force: bool = False):
    ticker = ticker.upper()

    # Cache: reuse prediction generated within the last hour unless force=True
    if not force:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cached = await db.predictions.find_one(
            {"ticker": ticker, "generated_at": {"$gte": cutoff}},
            {"_id": 0, "_pkey": 0},
            sort=[("generated_at", -1)],
        )
        if cached:
            cached["cached"] = True
            return cached

    mxn_rate = await get_usd_mxn_rate()
    quote = await fetch_quote(ticker, mxn_rate)
    history_rows = await asyncio.to_thread(_fetch_history_sync, ticker)

    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="LLM key missing")

    from emergentintegrations.llm.chat import LlmChat, UserMessage

    system_msg = (
        "You are a senior quantitative equity analyst. Given recent OHLC daily history (last ~30 days) "
        "and the latest quote of a NASDAQ/NYSE stock, produce a SHORT-TERM (next trading day) price forecast "
        "and curate 3 plausible recent news headlines that could influence the move. "
        "ALWAYS return STRICT JSON only, no prose, matching this schema: "
        "{\"prediction_price\": number, \"prediction_change_percent\": number, "
        "\"direction\": \"up\"|\"down\"|\"flat\", \"confidence\": \"low\"|\"medium\"|\"high\", "
        "\"rationale\": string (2-3 sentences), "
        "\"news\": [{\"title\": string, \"source\": string (Bloomberg|Yahoo Finance|Google Finance|Reuters|CNBC), "
        "\"summary\": string, \"sentiment\": \"positive\"|\"negative\"|\"neutral\"}]} "
        "Base the forecast on momentum, volatility and trend in the provided history. "
        "Keep predictions realistic (typically within +/-5% of current price)."
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"predict-{ticker}-{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
        system_message=system_msg,
    ).with_model("gemini", "gemini-3-flash-preview")

    payload = {
        "ticker": ticker,
        "name": quote.name,
        "current_price": quote.price,
        "open": quote.open,
        "high": quote.high,
        "previous_close": quote.previous_close,
        "change_percent": quote.change_percent,
        "history_last_30d": history_rows,
    }

    user_msg = UserMessage(text=json.dumps(payload))

    try:
        response_text = await chat.send_message(user_msg)
    except Exception as e:
        logger.error(f"LLM error: {e}")
        raise HTTPException(status_code=502, detail="AI prediction service unavailable")

    # Extract JSON from response
    cleaned = response_text.strip()
    # Strip possible code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Try to locate JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        logger.error(f"Could not parse LLM JSON: {response_text[:500]}")
        raise HTTPException(status_code=502, detail="AI returned invalid JSON")

    result = PredictionResponse(
        ticker=ticker,
        prediction_price=parsed.get("prediction_price"),
        prediction_change_percent=parsed.get("prediction_change_percent"),
        direction=str(parsed.get("direction", "flat")).lower(),
        confidence=str(parsed.get("confidence", "medium")).lower(),
        rationale=parsed.get("rationale", ""),
        news=parsed.get("news", []),
    )
    doc = result.model_dump()
    doc["generated_at"] = doc["generated_at"].isoformat()

    # Check for direction flip vs the previous stored prediction
    prev = await db.predictions.find_one(
        {"ticker": ticker},
        {"_id": 0, "direction": 1, "generated_at": 1, "prediction_price": 1},
        sort=[("generated_at", -1)],
    )
    await db.predictions.insert_one({**doc, "_pkey": f"{ticker}-{doc['generated_at']}"})

    if prev and prev.get("direction") and prev["direction"] != result.direction and result.direction in ("up", "down") and prev["direction"] in ("up", "down"):
        await _create_alert(
            ticker=ticker,
            atype="direction_flip",
            message=f"AI direction flipped {prev['direction'].upper()} → {result.direction.upper()} ({result.confidence} confidence)",
            payload={
                "from_direction": prev["direction"],
                "to_direction": result.direction,
                "prediction_price": result.prediction_price,
                "confidence": result.confidence,
            },
        )

    doc["cached"] = False
    return doc


@api_router.get("/compare")
async def compare(tickers: str):
    """Compare 2+ tickers' 30d normalized close (base 100)."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 tickers")
    if len(ticker_list) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 tickers")

    async def fetch(t):
        try:
            return t, await asyncio.to_thread(_fetch_history_sync, t)
        except Exception as e:
            logger.warning(f"compare fetch {t}: {e}")
            return t, []

    results = await asyncio.gather(*[fetch(t) for t in ticker_list])

    series = []
    for t, rows in results:
        if not rows:
            continue
        base = rows[0]["close"] or 1.0
        points = [
            {"date": r["date"], "value": round((r["close"] / base) * 100, 2), "raw": r["close"]}
            for r in rows
        ]
        change_pct = ((rows[-1]["close"] - rows[0]["close"]) / rows[0]["close"]) * 100 if rows[0]["close"] else 0
        series.append({
            "ticker": t,
            "points": points,
            "start": rows[0]["close"],
            "end": rows[-1]["close"],
            "change_percent": round(change_pct, 2),
        })

    if not series:
        raise HTTPException(status_code=404, detail="No data for provided tickers")

    return {"series": series, "tickers": [s["ticker"] for s in series]}


# ---------- Alerts ----------
PRICE_MOVE_THRESHOLD = 3.0  # percent


async def _create_alert(ticker: str, atype: str, message: str, payload: dict | None = None) -> dict:
    doc = {
        "id": str(uuid.uuid4()),
        "ticker": ticker.upper(),
        "type": atype,
        "message": message,
        "payload": payload or {},
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.alerts.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _check_price_moves(threshold: float = PRICE_MOVE_THRESHOLD) -> int:
    """Compare each watchlist ticker against last stored ticker_state price; alert if abs(move) >= threshold."""
    items = await db.watchlist.find({}, {"_id": 0}).to_list(500)
    tickers = [it["ticker"] for it in items]
    if not tickers:
        return 0
    mxn_rate = await get_usd_mxn_rate()
    created = 0
    for t in tickers:
        try:
            q = await fetch_quote(t, mxn_rate)
        except Exception as e:
            logger.warning(f"price-check fetch {t}: {e}")
            continue
        state = await db.ticker_state.find_one({"ticker": t}, {"_id": 0})
        prev_price = state.get("last_price") if state else None
        if prev_price and q.price:
            move = ((q.price - prev_price) / prev_price) * 100
            if abs(move) >= threshold:
                direction = "up" if move > 0 else "down"
                await _create_alert(
                    ticker=t,
                    atype="price_move",
                    message=f"{t} {direction} {move:+.2f}% to ${q.price:.2f}",
                    payload={
                        "from_price": prev_price,
                        "to_price": q.price,
                        "change_percent": round(move, 2),
                        "direction": direction,
                    },
                )
                created += 1
        await db.ticker_state.update_one(
            {"ticker": t},
            {"$set": {"last_price": q.price, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
    return created


@api_router.get("/alerts")
async def list_alerts(unread_only: bool = False, limit: int = 50):
    query = {"read": False} if unread_only else {}
    items = await db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    unread = await db.alerts.count_documents({"read": False})
    return {"alerts": items, "unread": unread, "total": await db.alerts.count_documents({})}


@api_router.post("/alerts/sync")
async def sync_alerts():
    # IMPORTANT: target/stop-loss check MUST run before price-move check,
    # because the latter overwrites ticker_state.last_price.
    target_created = await _check_target_crosses()
    created = await _check_price_moves()
    return {"created": created + target_created, "price_moves": created, "target_hits": target_created}


@api_router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str):
    res = await db.alerts.update_one({"id": alert_id}, {"$set": {"read": True}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": alert_id, "read": True}


@api_router.post("/alerts/read-all")
async def mark_all_read():
    res = await db.alerts.update_many({"read": False}, {"$set": {"read": True}})
    return {"updated": res.modified_count}


@api_router.delete("/alerts")
async def clear_alerts():
    res = await db.alerts.delete_many({})
    return {"deleted": res.deleted_count}


# ---------- Portfolio (positions, lots, targets) ----------
async def _aggregate_position(ticker: str, mxn_rate: float, current_price: Optional[float]):
    """Compute aggregated position metrics for a ticker."""
    lots = await db.position_lots.find({"ticker": ticker}, {"_id": 0}).sort("buy_date", 1).to_list(1000)
    if not lots:
        return None

    total_qty = 0.0
    total_cost_usd = 0.0
    total_cost_mxn = 0.0
    for lot in lots:
        qty = float(lot["qty"])
        price = float(lot["buy_price_usd"])
        fx = float(lot.get("buy_fx_rate") or mxn_rate)
        total_qty += qty
        total_cost_usd += qty * price
        total_cost_mxn += qty * price * fx

    avg_cost_usd = total_cost_usd / total_qty if total_qty else 0.0
    avg_cost_mxn = total_cost_mxn / total_qty if total_qty else 0.0

    target_doc = await db.position_targets.find_one({"ticker": ticker}, {"_id": 0})
    target_price = target_doc.get("target_price") if target_doc else None
    stop_loss_price = target_doc.get("stop_loss_price") if target_doc else None

    market_value_usd = (current_price or 0.0) * total_qty if current_price else None
    market_value_mxn = (market_value_usd * mxn_rate) if market_value_usd is not None else None
    pnl_usd = (market_value_usd - total_cost_usd) if market_value_usd is not None else None
    pnl_pct = (pnl_usd / total_cost_usd * 100) if (pnl_usd is not None and total_cost_usd) else None
    pnl_mxn = (market_value_mxn - total_cost_mxn) if market_value_mxn is not None else None

    target_distance_pct = None
    if target_price and current_price:
        target_distance_pct = ((target_price - current_price) / current_price) * 100
    stop_distance_pct = None
    if stop_loss_price and current_price:
        stop_distance_pct = ((current_price - stop_loss_price) / current_price) * 100

    target_pnl_usd = ((target_price - avg_cost_usd) * total_qty) if target_price else None
    target_pnl_pct = ((target_price - avg_cost_usd) / avg_cost_usd * 100) if (target_price and avg_cost_usd) else None

    return {
        "ticker": ticker,
        "qty": round(total_qty, 6),
        "avg_cost_usd": round(avg_cost_usd, 4),
        "avg_cost_mxn": round(avg_cost_mxn, 4),
        "total_cost_usd": round(total_cost_usd, 2),
        "total_cost_mxn": round(total_cost_mxn, 2),
        "current_price": current_price,
        "market_value_usd": round(market_value_usd, 2) if market_value_usd is not None else None,
        "market_value_mxn": round(market_value_mxn, 2) if market_value_mxn is not None else None,
        "pnl_usd": round(pnl_usd, 2) if pnl_usd is not None else None,
        "pnl_mxn": round(pnl_mxn, 2) if pnl_mxn is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "target_distance_pct": round(target_distance_pct, 2) if target_distance_pct is not None else None,
        "stop_distance_pct": round(stop_distance_pct, 2) if stop_distance_pct is not None else None,
        "target_pnl_usd": round(target_pnl_usd, 2) if target_pnl_usd is not None else None,
        "target_pnl_pct": round(target_pnl_pct, 2) if target_pnl_pct is not None else None,
        "lots_count": len(lots),
    }


@api_router.get("/portfolio")
async def get_portfolio():
    tickers = await db.position_lots.distinct("ticker")
    if not tickers:
        return {"positions": [], "totals": {"cost_usd": 0, "value_usd": 0, "pnl_usd": 0, "pnl_pct": 0, "cost_mxn": 0, "value_mxn": 0, "pnl_mxn": 0}, "mxn_rate": await get_usd_mxn_rate()}

    mxn_rate = await get_usd_mxn_rate()

    async def fetch_price(t):
        try:
            q = await fetch_quote(t, mxn_rate)
            return t, q.price
        except Exception as e:
            logger.warning(f"portfolio price fetch {t}: {e}")
            return t, None

    price_pairs = await asyncio.gather(*[fetch_price(t) for t in tickers])
    prices = {t: p for t, p in price_pairs}

    positions = []
    for t in tickers:
        pos = await _aggregate_position(t, mxn_rate, prices.get(t))
        if pos:
            positions.append(pos)

    cost_usd = sum(p["total_cost_usd"] for p in positions)
    cost_mxn = sum(p["total_cost_mxn"] for p in positions)
    value_usd = sum((p["market_value_usd"] or 0) for p in positions)
    value_mxn = sum((p["market_value_mxn"] or 0) for p in positions)
    pnl_usd = value_usd - cost_usd
    pnl_mxn = value_mxn - cost_mxn
    pnl_pct = (pnl_usd / cost_usd * 100) if cost_usd else 0

    return {
        "positions": positions,
        "totals": {
            "cost_usd": round(cost_usd, 2),
            "cost_mxn": round(cost_mxn, 2),
            "value_usd": round(value_usd, 2),
            "value_mxn": round(value_mxn, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_mxn": round(pnl_mxn, 2),
            "pnl_pct": round(pnl_pct, 2),
        },
        "mxn_rate": mxn_rate,
    }


@api_router.get("/portfolio/lots/{ticker}")
async def get_lots(ticker: str):
    ticker = ticker.upper()
    lots = await db.position_lots.find({"ticker": ticker}, {"_id": 0}).sort("buy_date", 1).to_list(1000)
    return {"ticker": ticker, "lots": lots}


@api_router.post("/portfolio/lots")
async def add_lot(req: AddLotRequest):
    ticker = req.ticker.strip().upper()
    if not ticker or not re.match(r"^[A-Z0-9.\-]{1,10}$", ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if req.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be > 0")
    if req.buy_price_usd <= 0:
        raise HTTPException(status_code=400, detail="buy_price_usd must be > 0")

    fx = req.buy_fx_rate if req.buy_fx_rate and req.buy_fx_rate > 0 else await get_usd_mxn_rate()
    buy_date = req.buy_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    doc = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "qty": float(req.qty),
        "buy_price_usd": float(req.buy_price_usd),
        "buy_fx_rate": float(fx),
        "buy_date": buy_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.position_lots.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@api_router.delete("/portfolio/lots/{lot_id}")
async def delete_lot(lot_id: str):
    res = await db.position_lots.delete_one({"id": lot_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lot not found")
    return {"id": lot_id, "deleted": True}


@api_router.put("/portfolio/target/{ticker}")
async def set_target(ticker: str, req: SetTargetRequest):
    ticker = ticker.upper()
    if req.target_price is None and req.stop_loss_price is None:
        raise HTTPException(status_code=400, detail="Provide target_price or stop_loss_price")
    if req.target_price is not None and req.target_price <= 0:
        raise HTTPException(status_code=400, detail="target_price must be > 0")
    if req.stop_loss_price is not None and req.stop_loss_price <= 0:
        raise HTTPException(status_code=400, detail="stop_loss_price must be > 0")

    update = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if req.target_price is not None:
        update["target_price"] = float(req.target_price)
    if req.stop_loss_price is not None:
        update["stop_loss_price"] = float(req.stop_loss_price)
    await db.position_targets.update_one({"ticker": ticker}, {"$set": update}, upsert=True)
    return {"ticker": ticker, **update}


@api_router.delete("/portfolio/target/{ticker}")
async def delete_target(ticker: str):
    ticker = ticker.upper()
    res = await db.position_targets.delete_one({"ticker": ticker})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Target not found")
    return {"ticker": ticker, "deleted": True}


async def _check_target_crosses() -> int:
    """Emit alerts when current price crosses a target (up) or stop-loss (down)."""
    targets = await db.position_targets.find({}, {"_id": 0}).to_list(500)
    if not targets:
        return 0
    mxn_rate = await get_usd_mxn_rate()
    created = 0
    for tgt in targets:
        ticker = tgt["ticker"]
        # only alert if user actually holds this ticker
        has_lots = await db.position_lots.find_one({"ticker": ticker}, {"_id": 0})
        if not has_lots:
            continue
        try:
            q = await fetch_quote(ticker, mxn_rate)
        except Exception as e:
            logger.warning(f"target check fetch {ticker}: {e}")
            continue
        state = await db.ticker_state.find_one({"ticker": ticker}, {"_id": 0}) or {}
        prev_price = state.get("last_price")
        if not prev_price or not q.price:
            continue

        target = tgt.get("target_price")
        sl = tgt.get("stop_loss_price")
        last_target_alert = state.get("last_target_alert_at")
        last_sl_alert = state.get("last_sl_alert_at")
        now_iso = datetime.now(timezone.utc).isoformat()
        recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()

        if target and prev_price < target <= q.price and (not last_target_alert or last_target_alert < recent_cutoff):
            await _create_alert(
                ticker=ticker,
                atype="target_hit",
                message=f"{ticker} crossed target ${target:.2f} — current ${q.price:.2f}",
                payload={"target_price": target, "current_price": q.price, "prev_price": prev_price},
            )
            await db.ticker_state.update_one({"ticker": ticker}, {"$set": {"last_target_alert_at": now_iso}}, upsert=True)
            created += 1
        if sl and prev_price > sl >= q.price and (not last_sl_alert or last_sl_alert < recent_cutoff):
            await _create_alert(
                ticker=ticker,
                atype="stop_loss_hit",
                message=f"{ticker} hit stop-loss ${sl:.2f} — current ${q.price:.2f}",
                payload={"stop_loss_price": sl, "current_price": q.price, "prev_price": prev_price},
            )
            await db.ticker_state.update_one({"ticker": ticker}, {"$set": {"last_sl_alert_at": now_iso}}, upsert=True)
            created += 1
    return created


# ---------- Background scheduler ----------
async def _alerts_loop():
    # initial delay to let app boot
    await asyncio.sleep(15)
    while True:
        try:
            # target check first — relies on the previous tick's last_price
            t = await _check_target_crosses()
            n = await _check_price_moves()
            total = (n or 0) + (t or 0)
            if total:
                logger.info(f"alerts_loop: {total} new alerts ({n} price, {t} target)")
        except Exception as e:
            logger.error(f"alerts_loop iteration failed: {e}")
        await asyncio.sleep(600)  # 10 minutes


@app.on_event("startup")
async def _on_startup():
    asyncio.create_task(_alerts_loop())


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
