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
