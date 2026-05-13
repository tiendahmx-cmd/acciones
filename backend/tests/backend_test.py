"""Backend API tests for Stock Tracker (yfinance + Emergent LLM + Frankfurter FX)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://nasdaq-watchlist.preview.emergentagent.com").rstrip("/")
# Read from frontend env to be safe
try:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                break
except Exception:
    pass

API = f"{BASE_URL}/api"
DEFAULT_TICKERS = ["INTC", "SMCI", "VIST", "DELL", "QCOM", "NTR", "MELI", "BABA", "TQQQ", "NVDA", "WDC", "SLV"]


# ---- Exchange Rate ----
def test_exchange_rate():
    r = requests.get(f"{API}/exchange-rate", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["base"] == "USD"
    assert data["target"] == "MXN"
    assert isinstance(data["rate"], (int, float)) and data["rate"] > 0
    assert "_id" not in data


# ---- Watchlist ----
def test_watchlist_default_seed():
    r = requests.get(f"{API}/watchlist", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "tickers" in data
    assert isinstance(data["tickers"], list)
    # Default tickers should be present (may have been added/removed by previous tests)
    for t in DEFAULT_TICKERS:
        assert t in data["tickers"], f"Missing default ticker {t}"
    assert "_id" not in str(data)


def test_watchlist_add_valid_then_remove():
    # Cleanup first if exists
    requests.delete(f"{API}/watchlist/AAPL", timeout=20)

    r = requests.post(f"{API}/watchlist", json={"ticker": "AAPL"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ticker"] == "AAPL"
    assert data["status"] in ("added", "exists")

    # Verify persistence
    wl = requests.get(f"{API}/watchlist", timeout=20).json()
    assert "AAPL" in wl["tickers"]

    # Idempotent - second add returns exists
    r2 = requests.post(f"{API}/watchlist", json={"ticker": "AAPL"}, timeout=30)
    assert r2.status_code == 200
    assert r2.json()["status"] == "exists"

    # Delete
    d = requests.delete(f"{API}/watchlist/AAPL", timeout=20)
    assert d.status_code == 200
    assert d.json()["ticker"] == "AAPL"

    # Verify removed
    wl2 = requests.get(f"{API}/watchlist", timeout=20).json()
    assert "AAPL" not in wl2["tickers"]


def test_watchlist_add_invalid():
    r = requests.post(f"{API}/watchlist", json={"ticker": "ZZZZZZZ"}, timeout=30)
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


def test_watchlist_delete_nonexistent():
    r = requests.delete(f"{API}/watchlist/NOPENOPE", timeout=20)
    assert r.status_code == 404


# ---- Quotes ----
def test_quotes_list():
    r = requests.get(f"{API}/quotes", timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "mxn_rate" in data and isinstance(data["mxn_rate"], (int, float)) and data["mxn_rate"] > 0
    assert "quotes" in data and isinstance(data["quotes"], list)
    assert len(data["quotes"]) > 0
    sample = data["quotes"][0]
    for field in ["ticker", "price", "change_percent", "open", "high", "price_mxn"]:
        assert field in sample, f"Missing field {field} in quote"
    assert sample["price"] is None or sample["price"] > 0
    assert "_id" not in str(data)


def test_single_quote():
    r = requests.get(f"{API}/quote/NVDA", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "mxn_rate" in data
    q = data["quote"]
    assert q["ticker"] == "NVDA"
    assert q["price"] is not None and q["price"] > 0
    assert q["price_mxn"] is not None and q["price_mxn"] > 0


# ---- History ----
def test_history_nvda():
    r = requests.get(f"{API}/history/NVDA", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ticker"] == "NVDA"
    assert isinstance(data["history"], list) and len(data["history"]) > 0
    row = data["history"][0]
    for field in ["date", "open", "high", "low", "close", "volume"]:
        assert field in row


# ---- AI Prediction ----
def test_predict_nvda():
    r = requests.post(f"{API}/predict/NVDA", timeout=90)
    assert r.status_code == 200, f"Predict failed: {r.status_code} {r.text[:500]}"
    data = r.json()
    assert data["ticker"] == "NVDA"
    assert "prediction_price" in data
    assert "prediction_change_percent" in data
    assert data["direction"] in ("up", "down", "flat")
    assert data["confidence"] in ("low", "medium", "high")
    assert isinstance(data["rationale"], str) and len(data["rationale"]) > 0
    assert isinstance(data["news"], list) and len(data["news"]) >= 1
    for n in data["news"]:
        for f in ["title", "source", "summary", "sentiment"]:
            assert f in n, f"News item missing {f}"
    assert "_id" not in str(data)


# ---- Iteration 2: Sparkline in quotes ----
def test_quotes_have_sparkline():
    r = requests.get(f"{API}/quotes", timeout=60)
    assert r.status_code == 200
    data = r.json()
    assert len(data["quotes"]) > 0
    for q in data["quotes"]:
        assert "sparkline" in q, f"Missing sparkline in {q.get('ticker')}"
        spark = q["sparkline"]
        assert isinstance(spark, list), f"sparkline not list for {q['ticker']}"
        assert len(spark) >= 10, f"sparkline too short for {q['ticker']}: {len(spark)}"
        # All entries should be floats
        for v in spark:
            assert isinstance(v, (int, float)), f"sparkline element not numeric for {q['ticker']}"


# ---- Iteration 2: Prediction cache ----
def test_predict_cache_flow_intc():
    # Force a fresh prediction first (bypass any prior cache)
    r1 = requests.post(f"{API}/predict/INTC?force=true", timeout=120)
    assert r1.status_code == 200, f"force predict failed: {r1.text[:500]}"
    d1 = r1.json()
    assert d1.get("cached") is False, f"force=true should return cached=False, got {d1.get('cached')}"
    price1 = d1["prediction_price"]
    assert "_id" not in str(d1)

    # Subsequent call within 1h should be cached
    t0 = time.time()
    r2 = requests.post(f"{API}/predict/INTC", timeout=30)
    elapsed = time.time() - t0
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("cached") is True, f"second call should be cached=True, got {d2.get('cached')}"
    assert d2["prediction_price"] == price1, "cached prediction_price differs from original"
    assert elapsed < 5, f"cached response took {elapsed:.2f}s, expected <5s"
    assert "_id" not in str(d2)

    # force=true bypasses cache
    r3 = requests.post(f"{API}/predict/INTC?force=true", timeout=120)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3.get("cached") is False, f"force=true should bypass cache, got cached={d3.get('cached')}"


# ---- Iteration 2: Compare endpoint ----
def test_compare_two_tickers():
    r = requests.get(f"{API}/compare", params={"tickers": "NVDA,AAPL"}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "series" in data
    assert isinstance(data["series"], list)
    assert len(data["series"]) == 2
    tickers_seen = set()
    for s in data["series"]:
        for f in ["ticker", "points", "change_percent", "start", "end"]:
            assert f in s, f"Compare series missing field {f}"
        assert isinstance(s["points"], list) and len(s["points"]) > 0
        for p in s["points"]:
            assert "date" in p and "value" in p
        tickers_seen.add(s["ticker"])
    assert tickers_seen == {"NVDA", "AAPL"}
    assert "_id" not in str(data)


def test_compare_too_few_tickers():
    r = requests.get(f"{API}/compare", params={"tickers": "NVDA"}, timeout=30)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


def test_compare_too_many_tickers():
    r = requests.get(f"{API}/compare", params={"tickers": "A,B,C,D,E"}, timeout=30)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


def test_compare_partial_invalid_ticker():
    r = requests.get(f"{API}/compare", params={"tickers": "NVDA,ZZZZZZZ"}, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["series"]) == 1
    assert data["series"][0]["ticker"] == "NVDA"
