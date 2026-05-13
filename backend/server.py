from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import json
import re
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


class PredictionResponse(BaseModel):
    ticker: str
    prediction_price: Optional[float] = None
    prediction_change_percent: Optional[float] = None
    direction: str
    confidence: str
    rationale: str
    news: List[dict] = []
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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

    hist = t.history(period="2d", interval="1d", auto_adjust=False)
    price = open_p = high = low = prev_close = None
    volume = None
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
async def predict(ticker: str):
    ticker = ticker.upper()
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
    await db.predictions.insert_one({**doc, "_pkey": f"{ticker}-{doc['generated_at']}"})
    return result.model_dump()


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
