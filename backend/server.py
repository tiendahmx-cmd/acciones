from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
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
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
import math
import bcrypt
import jwt


def _clean_float(v):
    """Return None for NaN/inf floats so JSON serialization doesn't fail."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# MongoDB
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# Emergent LLM
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")

# JWT
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

app = FastAPI()
api_router = APIRouter(prefix="/api")
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------- Auth helpers ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    token: Optional[str] = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token inválido")
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def is_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def needs_scope(user: dict, request: Request) -> bool:
    """Admin can opt-out of user scoping via ?admin_all=true; everyone else is always scoped."""
    if is_admin(user) and request.query_params.get("admin_all") == "true":
        return False
    return True


def user_filter(user: dict, request: Request, extra: Optional[dict] = None) -> dict:
    f = dict(extra) if extra else {}
    if needs_scope(user, request):
        f["user_id"] = user["id"]
    return f


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Acceso solo para administradores")
    return current_user

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


class SellRequest(BaseModel):
    ticker: str
    qty: float
    sell_price_usd: float
    sell_fx_rate: Optional[float] = None
    sell_date: Optional[str] = None
    method: str = "FIFO"  # FIFO | LIFO | SPECIFIC
    lot_ids: Optional[List[str]] = None  # required when method=SPECIFIC


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
        sparkline = [round(float(v), 2) for v in hist["Close"].tolist() if v is not None and not (isinstance(v, float) and math.isnan(v))]

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
        "price": _clean_float(price),
        "change": _clean_float(change),
        "change_percent": _clean_float(change_percent),
        "open": _clean_float(open_p),
        "high": _clean_float(high),
        "low": _clean_float(low),
        "previous_close": _clean_float(prev_close),
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


async def ensure_default_watchlist(user_id: str):
    count = await db.watchlist.count_documents({"user_id": user_id})
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        docs = [{"user_id": user_id, "ticker": t, "added_at": now} for t in DEFAULT_TICKERS]
        await db.watchlist.insert_many(docs)


# ---------- Routes ----------
@api_router.get("/")
async def root():
    return {"message": "Stock Tracker API"}


# ---------- Auth endpoints ----------
@auth_router.post("/register")
async def register(req: RegisterRequest):
    email = req.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Ese email ya está registrado")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": email,
        "name": req.name or email.split("@")[0],
        "password_hash": hash_password(req.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    token = create_access_token(user_id, email)
    return {
        "token": token,
        "user": {"id": user_id, "email": email, "name": doc["name"], "role": "user"},
    }


@auth_router.post("/login")
async def login(req: LoginRequest, request: Request):
    email = req.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}:{email}"

    # Brute-force: 5 attempts -> 15 min lockout
    attempt = await db.login_attempts.find_one({"identifier": key})
    now = datetime.now(timezone.utc)
    if attempt:
        locked_until = attempt.get("locked_until")
        if locked_until and datetime.fromisoformat(locked_until) > now:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Intenta en unos minutos.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user["password_hash"]):
        fails = (attempt.get("fails", 0) if attempt else 0) + 1
        update = {"identifier": key, "fails": fails, "last_at": now.isoformat()}
        if fails >= 5:
            update["locked_until"] = (now + timedelta(minutes=15)).isoformat()
            update["fails"] = 0
        await db.login_attempts.update_one({"identifier": key}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    await db.login_attempts.delete_one({"identifier": key})
    token = create_access_token(user["id"], user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user.get("name"), "role": user.get("role", "user")},
    }


@auth_router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    return {"ok": True}


@auth_router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {"user": {"id": current_user["id"], "email": current_user["email"], "name": current_user.get("name"), "role": current_user.get("role", "user")}}


@api_router.get("/exchange-rate")
async def exchange_rate():
    rate = await get_usd_mxn_rate()
    return {"base": "USD", "target": "MXN", "rate": rate, "fetched_at": datetime.now(timezone.utc).isoformat()}


@api_router.get("/watchlist")
async def get_watchlist(current_user: dict = Depends(get_current_user)):
    await ensure_default_watchlist(current_user["id"])
    items = await db.watchlist.find({"user_id": current_user["id"]}, {"_id": 0}).sort("added_at", 1).to_list(500)
    return {"tickers": [it["ticker"] for it in items]}


@api_router.post("/watchlist")
async def add_to_watchlist(req: AddStockRequest, current_user: dict = Depends(get_current_user)):
    ticker = req.ticker.strip().upper()
    if not ticker or not re.match(r"^[A-Z0-9.\-]{1,10}$", ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    # Validate ticker exists
    try:
        rate = await get_usd_mxn_rate()
        await fetch_quote(ticker, rate)
    except HTTPException as e:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    existing = await db.watchlist.find_one({"user_id": current_user["id"], "ticker": ticker})
    if existing:
        return {"ticker": ticker, "status": "exists"}
    await db.watchlist.insert_one({"user_id": current_user["id"], "ticker": ticker, "added_at": datetime.now(timezone.utc).isoformat()})
    return {"ticker": ticker, "status": "added"}


@api_router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, current_user: dict = Depends(get_current_user)):
    ticker = ticker.strip().upper()
    res = await db.watchlist.delete_one({"user_id": current_user["id"], "ticker": ticker})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    return {"ticker": ticker, "status": "removed"}


@api_router.get("/quotes")
async def quotes(tickers: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    await ensure_default_watchlist(current_user["id"])
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        items = await db.watchlist.find({"user_id": current_user["id"]}, {"_id": 0}).sort("added_at", 1).to_list(500)
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
async def single_quote(ticker: str, current_user: dict = Depends(get_current_user)):
    mxn_rate = await get_usd_mxn_rate()
    q = await fetch_quote(ticker.upper(), mxn_rate)
    return {"mxn_rate": mxn_rate, "quote": q.model_dump()}


@api_router.get("/history/{ticker}")
async def history(ticker: str, current_user: dict = Depends(get_current_user)):
    rows = await asyncio.to_thread(_fetch_history_sync, ticker.upper())
    if not rows:
        raise HTTPException(status_code=404, detail="No history available")
    return {"ticker": ticker.upper(), "history": rows}


@api_router.post("/predict/{ticker}")
async def predict(ticker: str, request: Request, force: bool = False, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper()

    # Cache: reuse prediction generated within the last hour unless force=True
    if not force:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cached = await db.predictions.find_one(
            {"user_id": current_user["id"], "ticker": ticker, "generated_at": {"$gte": cutoff}},
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
        {"user_id": current_user["id"], "ticker": ticker},
        {"_id": 0, "direction": 1, "generated_at": 1, "prediction_price": 1},
        sort=[("generated_at", -1)],
    )
    await db.predictions.insert_one({**doc, "user_id": current_user["id"], "_pkey": f"{current_user['id']}-{ticker}-{doc['generated_at']}"})

    if prev and prev.get("direction") and prev["direction"] != result.direction and result.direction in ("up", "down") and prev["direction"] in ("up", "down"):
        await _create_alert(
            user_id=current_user["id"],
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
async def compare(tickers: str, current_user: dict = Depends(get_current_user)):
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


async def _create_alert(ticker: str, atype: str, message: str, payload: dict | None = None, user_id: Optional[str] = None) -> dict:
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
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
    """For every (user_id, ticker) in watchlists, compare current price vs ticker_state.last_price;
    alert that user if abs(move) >= threshold. ticker_state is global (shared) since the price is shared.
    """
    distinct_tickers = await db.watchlist.distinct("ticker")
    if not distinct_tickers:
        return 0
    mxn_rate = await get_usd_mxn_rate()
    created = 0
    for t in distinct_tickers:
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
                # Find every user that holds this ticker in their watchlist
                watchers = await db.watchlist.find({"ticker": t}, {"_id": 0, "user_id": 1}).to_list(10000)
                for w in watchers:
                    await _create_alert(
                        user_id=w["user_id"],
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
async def list_alerts(request: Request, unread_only: bool = False, limit: int = 50, current_user: dict = Depends(get_current_user)):
    base = {"read": False} if unread_only else {}
    q = user_filter(current_user, request, base)
    items = await db.alerts.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    scope = user_filter(current_user, request)
    unread = await db.alerts.count_documents({**scope, "read": False})
    total = await db.alerts.count_documents(scope)
    return {"alerts": items, "unread": unread, "total": total}


@api_router.post("/alerts/sync")
async def sync_alerts(current_user: dict = Depends(get_current_user)):
    # IMPORTANT: target/stop-loss check MUST run before price-move check,
    # because the latter overwrites ticker_state.last_price.
    target_created = await _check_target_crosses()
    created = await _check_price_moves()
    return {"created": created + target_created, "price_moves": created, "target_hits": target_created}


@api_router.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str, current_user: dict = Depends(get_current_user)):
    q = {"id": alert_id} if is_admin(current_user) else {"id": alert_id, "user_id": current_user["id"]}
    res = await db.alerts.update_one(q, {"$set": {"read": True}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": alert_id, "read": True}


@api_router.post("/alerts/read-all")
async def mark_all_read(request: Request, current_user: dict = Depends(get_current_user)):
    q = user_filter(current_user, request, {"read": False})
    res = await db.alerts.update_many(q, {"$set": {"read": True}})
    return {"updated": res.modified_count}


@api_router.delete("/alerts")
async def clear_alerts(request: Request, current_user: dict = Depends(get_current_user)):
    q = user_filter(current_user, request)
    res = await db.alerts.delete_many(q)
    return {"deleted": res.deleted_count}


# ---------- Portfolio (positions, lots, targets) ----------
async def _aggregate_position(user_id: str, ticker: str, mxn_rate: float, current_price: Optional[float]):
    """Compute aggregated position metrics for a ticker for a specific user."""
    lots = await db.position_lots.find({"user_id": user_id, "ticker": ticker}, {"_id": 0}).sort("buy_date", 1).to_list(1000)
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

    target_doc = await db.position_targets.find_one({"user_id": user_id, "ticker": ticker}, {"_id": 0})
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
async def get_portfolio(request: Request, current_user: dict = Depends(get_current_user)):
    scope = user_filter(current_user, request)
    # Aggregate per (user_id, ticker). Skip ownerless legacy docs just in case.
    pipeline = [
        {"$match": {**scope, "user_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": {"user_id": "$user_id", "ticker": "$ticker"}}},
    ]
    pairs = await db.position_lots.aggregate(pipeline).to_list(10000)
    mxn_rate = await get_usd_mxn_rate()
    if not pairs:
        return {"positions": [], "totals": {"cost_usd": 0, "value_usd": 0, "pnl_usd": 0, "pnl_pct": 0, "cost_mxn": 0, "value_mxn": 0, "pnl_mxn": 0}, "mxn_rate": mxn_rate}

    distinct_tickers = list({p["_id"]["ticker"] for p in pairs})

    async def fetch_price(t):
        try:
            q = await fetch_quote(t, mxn_rate)
            return t, q.price
        except Exception as e:
            logger.warning(f"portfolio price fetch {t}: {e}")
            return t, None

    price_pairs = await asyncio.gather(*[fetch_price(t) for t in distinct_tickers])
    prices = {t: p for t, p in price_pairs}

    positions = []
    for p in pairs:
        uid = p["_id"].get("user_id")
        t = p["_id"].get("ticker")
        if not uid or not t:
            continue
        pos = await _aggregate_position(uid, t, mxn_rate, prices.get(t))
        if pos:
            pos["user_id"] = uid
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
async def get_lots(ticker: str, request: Request, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper()
    scope = user_filter(current_user, request, {"ticker": ticker})
    lots = await db.position_lots.find(scope, {"_id": 0}).sort("buy_date", 1).to_list(1000)
    return {"ticker": ticker, "lots": lots}


@api_router.post("/portfolio/lots")
async def add_lot(req: AddLotRequest, current_user: dict = Depends(get_current_user)):
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
        "user_id": current_user["id"],
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
async def delete_lot(lot_id: str, current_user: dict = Depends(get_current_user)):
    q = {"id": lot_id} if is_admin(current_user) else {"id": lot_id, "user_id": current_user["id"]}
    res = await db.position_lots.delete_one(q)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lot not found")
    return {"id": lot_id, "deleted": True}


@api_router.put("/portfolio/target/{ticker}")
async def set_target(ticker: str, req: SetTargetRequest, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper()
    if req.target_price is None and req.stop_loss_price is None:
        raise HTTPException(status_code=400, detail="Provide target_price or stop_loss_price")
    if req.target_price is not None and req.target_price <= 0:
        raise HTTPException(status_code=400, detail="target_price must be > 0")
    if req.stop_loss_price is not None and req.stop_loss_price <= 0:
        raise HTTPException(status_code=400, detail="stop_loss_price must be > 0")

    update = {"user_id": current_user["id"], "updated_at": datetime.now(timezone.utc).isoformat()}
    if req.target_price is not None:
        update["target_price"] = float(req.target_price)
    if req.stop_loss_price is not None:
        update["stop_loss_price"] = float(req.stop_loss_price)
    await db.position_targets.update_one({"user_id": current_user["id"], "ticker": ticker}, {"$set": update}, upsert=True)
    return {"ticker": ticker, **update}


@api_router.delete("/portfolio/target/{ticker}")
async def delete_target(ticker: str, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper()
    q = {"ticker": ticker} if is_admin(current_user) else {"user_id": current_user["id"], "ticker": ticker}
    res = await db.position_targets.delete_one(q)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Target not found")
    return {"ticker": ticker, "deleted": True}


# ---------- Sell (close trade) ----------
@api_router.post("/portfolio/sell")
async def sell_position(req: SellRequest, current_user: dict = Depends(get_current_user)):
    ticker = req.ticker.strip().upper()
    if req.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be > 0")
    if req.sell_price_usd <= 0:
        raise HTTPException(status_code=400, detail="sell_price_usd must be > 0")
    method = (req.method or "FIFO").upper()
    if method not in ("FIFO", "LIFO", "SPECIFIC"):
        raise HTTPException(status_code=400, detail="method must be FIFO, LIFO or SPECIFIC")

    lots = await db.position_lots.find({"user_id": current_user["id"], "ticker": ticker}, {"_id": 0}).to_list(1000)
    if not lots:
        raise HTTPException(status_code=404, detail=f"No lots for {ticker}")

    total_qty = sum(float(l["qty"]) for l in lots)
    if req.qty - total_qty > 1e-9:
        raise HTTPException(status_code=400, detail=f"qty {req.qty} exceeds position {total_qty}")

    # Sort lots according to method
    if method == "FIFO":
        lots.sort(key=lambda l: l.get("buy_date", ""))
    elif method == "LIFO":
        lots.sort(key=lambda l: l.get("buy_date", ""), reverse=True)
    else:  # SPECIFIC
        if not req.lot_ids:
            raise HTTPException(status_code=400, detail="lot_ids required for SPECIFIC method")
        lot_map = {l["id"]: l for l in lots}
        ordered = []
        for lid in req.lot_ids:
            if lid not in lot_map:
                raise HTTPException(status_code=400, detail=f"lot {lid} not found")
            ordered.append(lot_map[lid])
        lots = ordered
        avail = sum(float(l["qty"]) for l in lots)
        if req.qty - avail > 1e-9:
            raise HTTPException(status_code=400, detail=f"selected lots provide only {avail} shares")

    sell_fx = req.sell_fx_rate if req.sell_fx_rate and req.sell_fx_rate > 0 else await get_usd_mxn_rate()
    sell_date = req.sell_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sell_price = float(req.sell_price_usd)

    remaining = float(req.qty)
    allocations = []
    cost_usd_total = 0.0
    cost_mxn_total = 0.0
    weighted_days = 0.0

    try:
        sell_dt = datetime.strptime(sell_date, "%Y-%m-%d")
    except Exception:
        sell_dt = datetime.now(timezone.utc)

    for lot in lots:
        if remaining <= 1e-9:
            break
        lot_qty = float(lot["qty"])
        consumed = min(lot_qty, remaining)
        buy_price = float(lot["buy_price_usd"])
        buy_fx = float(lot.get("buy_fx_rate") or sell_fx)
        try:
            buy_dt = datetime.strptime(lot.get("buy_date", sell_date), "%Y-%m-%d")
        except Exception:
            buy_dt = sell_dt
        days = max(0, (sell_dt - buy_dt).days)

        cost_usd = buy_price * consumed
        cost_mxn = buy_price * consumed * buy_fx
        proceeds_usd = sell_price * consumed
        proceeds_mxn = sell_price * consumed * sell_fx
        pnl_usd = proceeds_usd - cost_usd
        pnl_mxn = proceeds_mxn - cost_mxn

        cost_usd_total += cost_usd
        cost_mxn_total += cost_mxn
        weighted_days += days * consumed

        allocations.append({
            "lot_id": lot["id"],
            "qty": round(consumed, 6),
            "buy_price_usd": round(buy_price, 4),
            "buy_fx_rate": round(buy_fx, 4),
            "buy_date": lot.get("buy_date"),
            "days_held": days,
            "cost_usd": round(cost_usd, 2),
            "cost_mxn": round(cost_mxn, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_mxn": round(pnl_mxn, 2),
        })

        new_qty = lot_qty - consumed
        if new_qty <= 1e-9:
            await db.position_lots.delete_one({"id": lot["id"]})
        else:
            await db.position_lots.update_one({"id": lot["id"]}, {"$set": {"qty": round(new_qty, 6)}})

        remaining -= consumed

    sold_qty = float(req.qty)
    proceeds_usd = sell_price * sold_qty
    proceeds_mxn = sell_price * sold_qty * sell_fx
    pnl_usd = proceeds_usd - cost_usd_total
    pnl_mxn = proceeds_mxn - cost_mxn_total
    return_pct = (pnl_usd / cost_usd_total * 100) if cost_usd_total else 0
    avg_days = (weighted_days / sold_qty) if sold_qty else 0
    annualized = None
    if cost_usd_total and avg_days > 0 and proceeds_usd > 0:
        try:
            annualized = ((proceeds_usd / cost_usd_total) ** (365 / max(avg_days, 1)) - 1) * 100
            if math.isnan(annualized) or math.isinf(annualized):
                annualized = None
        except Exception:
            annualized = None

    trade_doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "ticker": ticker,
        "qty_sold": round(sold_qty, 6),
        "sell_price_usd": round(sell_price, 4),
        "sell_fx_rate": round(sell_fx, 4),
        "sell_date": sell_date,
        "method": method,
        "allocations": allocations,
        "cost_usd": round(cost_usd_total, 2),
        "cost_mxn": round(cost_mxn_total, 2),
        "proceeds_usd": round(proceeds_usd, 2),
        "proceeds_mxn": round(proceeds_mxn, 2),
        "pnl_usd": round(pnl_usd, 2),
        "pnl_mxn": round(pnl_mxn, 2),
        "return_pct": round(return_pct, 2),
        "avg_days_held": round(avg_days, 1),
        "annualized_return_pct": round(annualized, 2) if annualized is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.closed_trades.insert_one(trade_doc)
    return {k: v for k, v in trade_doc.items() if k != "_id"}


@api_router.get("/portfolio/trades")
async def list_trades(request: Request, limit: int = 200, current_user: dict = Depends(get_current_user)):
    scope = user_filter(current_user, request)
    trades = await db.closed_trades.find(scope, {"_id": 0}).sort("sell_date", -1).to_list(limit)
    total_pnl_usd = sum(t.get("pnl_usd", 0) for t in trades)
    total_pnl_mxn = sum(t.get("pnl_mxn", 0) for t in trades)
    total_cost = sum(t.get("cost_usd", 0) for t in trades)
    wins = sum(1 for t in trades if t.get("pnl_usd", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl_usd", 0) < 0)
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided else 0
    return {
        "trades": trades,
        "summary": {
            "count": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "total_pnl_usd": round(total_pnl_usd, 2),
            "total_pnl_mxn": round(total_pnl_mxn, 2),
            "total_cost_usd": round(total_cost, 2),
            "total_return_pct": round(total_pnl_usd / total_cost * 100, 2) if total_cost else 0,
        },
    }


@api_router.get("/portfolio/trades/equity-curve")
async def trades_equity_curve(request: Request, current_user: dict = Depends(get_current_user)):
    scope = user_filter(current_user, request)
    trades = await db.closed_trades.find(scope, {"_id": 0}).sort("sell_date", 1).to_list(2000)
    monthly: dict = {}
    for t in trades:
        sd = t.get("sell_date") or ""
        if len(sd) < 7:
            continue
        key = sd[:7]  # YYYY-MM
        m = monthly.setdefault(key, {"month": key, "pnl_usd": 0.0, "pnl_mxn": 0.0, "trades": 0})
        m["pnl_usd"] += float(t.get("pnl_usd", 0))
        m["pnl_mxn"] += float(t.get("pnl_mxn", 0))
        m["trades"] += 1

    points = sorted(monthly.values(), key=lambda x: x["month"])
    cum_usd = 0.0
    cum_mxn = 0.0
    for p in points:
        cum_usd += p["pnl_usd"]
        cum_mxn += p["pnl_mxn"]
        p["cumulative_usd"] = round(cum_usd, 2)
        p["cumulative_mxn"] = round(cum_mxn, 2)
        p["pnl_usd"] = round(p["pnl_usd"], 2)
        p["pnl_mxn"] = round(p["pnl_mxn"], 2)
    return {"points": points}


@api_router.delete("/portfolio/trades/{trade_id}")
async def delete_trade(trade_id: str, current_user: dict = Depends(get_current_user)):
    q = {"id": trade_id} if is_admin(current_user) else {"id": trade_id, "user_id": current_user["id"]}
    res = await db.closed_trades.delete_one(q)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"id": trade_id, "deleted": True}


# ---------- Admin endpoints ----------
@api_router.get("/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(10000)
    enriched = []
    for u in users:
        uid = u["id"]
        watchlist = await db.watchlist.count_documents({"user_id": uid})
        lots = await db.position_lots.count_documents({"user_id": uid})
        trades = await db.closed_trades.count_documents({"user_id": uid})
        alerts = await db.alerts.count_documents({"user_id": uid})
        unread = await db.alerts.count_documents({"user_id": uid, "read": False})
        enriched.append({
            **u,
            "stats": {"watchlist": watchlist, "lots": lots, "trades": trades, "alerts": alerts, "unread_alerts": unread},
        })
    return {"users": enriched, "count": len(enriched)}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    # Cascade delete all user data
    await db.watchlist.delete_many({"user_id": user_id})
    await db.position_lots.delete_many({"user_id": user_id})
    await db.position_targets.delete_many({"user_id": user_id})
    await db.closed_trades.delete_many({"user_id": user_id})
    await db.alerts.delete_many({"user_id": user_id})
    await db.predictions.delete_many({"user_id": user_id})
    await db.users.delete_one({"id": user_id})
    return {"id": user_id, "deleted": True}


async def _check_target_crosses() -> int:
    """Emit alerts per (user_id, ticker) when current price crosses target or stop-loss."""
    targets = await db.position_targets.find({}, {"_id": 0}).to_list(5000)
    if not targets:
        return 0
    mxn_rate = await get_usd_mxn_rate()
    created = 0
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    for tgt in targets:
        ticker = tgt["ticker"]
        uid = tgt.get("user_id")
        if not uid:
            continue
        # only alert if user actually holds this ticker
        has_lots = await db.position_lots.find_one({"user_id": uid, "ticker": ticker}, {"_id": 0})
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

        if target and prev_price < target <= q.price:
            recent_th = await db.alerts.find_one(
                {"user_id": uid, "ticker": ticker, "type": "target_hit", "created_at": {"$gte": cutoff_iso}},
                {"_id": 0},
            )
            if not recent_th:
                await _create_alert(
                    user_id=uid,
                    ticker=ticker,
                    atype="target_hit",
                    message=f"{ticker} crossed target ${target:.2f} — current ${q.price:.2f}",
                    payload={"target_price": target, "current_price": q.price, "prev_price": prev_price},
                )
                created += 1
        if sl and prev_price > sl >= q.price:
            recent_sl = await db.alerts.find_one(
                {"user_id": uid, "ticker": ticker, "type": "stop_loss_hit", "created_at": {"$gte": cutoff_iso}},
                {"_id": 0},
            )
            if not recent_sl:
                await _create_alert(
                    user_id=uid,
                    ticker=ticker,
                    atype="stop_loss_hit",
                    message=f"{ticker} hit stop-loss ${sl:.2f} — current ${q.price:.2f}",
                    payload={"stop_loss_price": sl, "current_price": q.price, "prev_price": prev_price},
                )
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
    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")

    # One-shot migration: delete ownerless documents from per-user collections (pre-auth legacy).
    for col_name in ("watchlist", "position_lots", "position_targets", "closed_trades", "alerts", "predictions"):
        col = db[col_name]
        res = await col.delete_many({"$or": [{"user_id": {"$exists": False}}, {"user_id": None}]})
        if res.deleted_count:
            logger.info(f"Migration: deleted {res.deleted_count} ownerless docs from {col_name}")

    # Seed/upgrade admin from env (password also syncs if .env changes)
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_email and admin_password:
        email_norm = admin_email.lower().strip()
        existing = await db.users.find_one({"email": email_norm})
        if not existing:
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": email_norm,
                "name": "Administrator",
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"Seeded admin user: {admin_email}")
        else:
            update = {"role": "admin"}
            # Sync password if .env has been changed
            if not verify_password(admin_password, existing.get("password_hash", "")):
                update["password_hash"] = hash_password(admin_password)
                logger.info("Admin password synced from .env")
            await db.users.update_one({"id": existing["id"]}, {"$set": update})

    asyncio.create_task(_alerts_loop())


app.include_router(auth_router)
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
