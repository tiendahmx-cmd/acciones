"""Iteration 3: Alerts (price_move + direction_flip) backend tests.

Uses direct Mongo manipulation (pymongo) to seed ticker_state / predictions
so we can deterministically force alerts without waiting for real price moves.
"""
import os
import time
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient


def _backend_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip().strip('"')
                    break
    return url.rstrip("/")


def _mongo_env():
    mongo_url = None
    db_name = None
    with open("/app/backend/.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("MONGO_URL="):
                mongo_url = line.split("=", 1)[1].strip().strip('"')
            if line.startswith("DB_NAME="):
                db_name = line.split("=", 1)[1].strip().strip('"')
    return mongo_url, db_name


BASE_URL = _backend_url()
API = f"{BASE_URL}/api"
MONGO_URL, DB_NAME = _mongo_env()


@pytest.fixture(scope="module")
def mdb():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture
def clean_alerts(mdb):
    mdb.alerts.delete_many({})
    yield
    # No cleanup here — done in final teardown test


# ---- Basic listing ----
def test_alerts_list_empty_shape(clean_alerts):
    r = requests.get(f"{API}/alerts", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "alerts" in data and isinstance(data["alerts"], list)
    assert data["alerts"] == []
    assert data["unread"] == 0
    assert data["total"] == 0
    assert "_id" not in str(data)


# ---- Sync seeds ticker_state on first call ----
def test_alerts_sync_first_call_seeds_state(mdb, clean_alerts):
    # Wipe ticker_state to simulate first run
    mdb.ticker_state.delete_many({})

    r = requests.post(f"{API}/alerts/sync", timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["created"] == 0, f"First sync should create 0 alerts, got {data['created']}"

    # ticker_state should now be populated for watchlist tickers
    state_count = mdb.ticker_state.count_documents({})
    assert state_count > 0, "ticker_state was not seeded"


# ---- Forced price_move alert via manipulated state ----
def test_alerts_sync_creates_price_move_alert(mdb, clean_alerts):
    # Pick a ticker known to be in default watchlist
    target = "NVDA"

    # First make sure ticker_state row exists by running a sync (or by getting current price via /quote)
    q = requests.get(f"{API}/quote/{target}", timeout=30).json()
    cur_price = q["quote"]["price"]
    assert cur_price and cur_price > 0

    # Set the stored last_price ~30% LOWER than current so next sync detects an "up" move
    fake_prev = round(cur_price * 0.7, 2)
    mdb.ticker_state.update_one(
        {"ticker": target},
        {"$set": {"last_price": fake_prev, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    r = requests.post(f"{API}/alerts/sync", timeout=120)
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert created >= 1, f"Expected >=1 alert created, got {created}"

    # Fetch alerts and validate document shape
    al = requests.get(f"{API}/alerts", timeout=20).json()
    assert al["total"] >= 1
    assert al["unread"] >= 1
    # Find the alert for our target
    matched = [a for a in al["alerts"] if a["ticker"] == target and a["type"] == "price_move"]
    assert len(matched) >= 1, f"No price_move alert for {target} found in {al['alerts']}"
    a = matched[0]
    for field in ["id", "ticker", "type", "message", "payload", "read", "created_at"]:
        assert field in a, f"Missing field {field}"
    assert a["type"] == "price_move"
    assert a["read"] is False
    assert isinstance(a["message"], str) and len(a["message"]) > 0
    assert isinstance(a["created_at"], str)
    # Validate ISO format parses
    datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
    p = a["payload"]
    for k in ["from_price", "to_price", "change_percent", "direction"]:
        assert k in p, f"Payload missing {k}"
    assert p["from_price"] == fake_prev
    assert p["direction"] == "up"
    assert p["change_percent"] > 0
    assert "_id" not in str(al)


# ---- Mark single alert read + 404 case ----
def test_mark_alert_read_and_not_found(mdb, clean_alerts):
    # Seed an alert directly via Mongo
    mdb.alerts.insert_one({
        "id": "test-alert-1",
        "ticker": "NVDA",
        "type": "price_move",
        "message": "test",
        "payload": {},
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    r = requests.post(f"{API}/alerts/test-alert-1/read", timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "test-alert-1", "read": True}

    # Verify persisted
    doc = mdb.alerts.find_one({"id": "test-alert-1"})
    assert doc["read"] is True

    # Non-existent → 404
    r2 = requests.post(f"{API}/alerts/does-not-exist-xyz/read", timeout=20)
    assert r2.status_code == 404


# ---- Mark all read ----
def test_mark_all_read(mdb, clean_alerts):
    now_iso = datetime.now(timezone.utc).isoformat()
    mdb.alerts.insert_many([
        {"id": f"a-{i}", "ticker": "NVDA", "type": "price_move", "message": "x",
         "payload": {}, "read": False, "created_at": now_iso}
        for i in range(3)
    ])
    r = requests.post(f"{API}/alerts/read-all", timeout=20)
    assert r.status_code == 200
    assert r.json()["updated"] == 3
    assert mdb.alerts.count_documents({"read": False}) == 0


# ---- Delete (clear) all ----
def test_clear_alerts(mdb, clean_alerts):
    now_iso = datetime.now(timezone.utc).isoformat()
    mdb.alerts.insert_many([
        {"id": f"d-{i}", "ticker": "NVDA", "type": "price_move", "message": "x",
         "payload": {}, "read": False, "created_at": now_iso}
        for i in range(4)
    ])
    r = requests.delete(f"{API}/alerts", timeout=20)
    assert r.status_code == 200
    assert r.json()["deleted"] == 4
    assert mdb.alerts.count_documents({}) == 0


# ---- Direction flip alert via /api/predict ----
def test_direction_flip_alert(mdb, clean_alerts):
    ticker = "QCOM"
    # Insert a fake previous prediction with direction='down'
    mdb.predictions.delete_many({"ticker": ticker})
    mdb.predictions.insert_one({
        "ticker": ticker,
        "prediction_price": 100.0,
        "prediction_change_percent": -2.0,
        "direction": "down",
        "confidence": "medium",
        "rationale": "seed",
        "news": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "_pkey": f"{ticker}-seed",
    })

    # Force a new prediction
    r = requests.post(f"{API}/predict/{ticker}?force=true", timeout=120)
    assert r.status_code == 200, r.text
    new_pred = r.json()
    new_dir = new_pred["direction"]

    # Check alert list — direction_flip should only exist if new_dir flipped to up/down (not flat)
    al = requests.get(f"{API}/alerts", timeout=20).json()
    flip_alerts = [a for a in al["alerts"] if a["ticker"] == ticker and a["type"] == "direction_flip"]
    if new_dir in ("up",):  # flip down->up is the real flip
        assert len(flip_alerts) >= 1, f"Expected direction_flip alert (down->{new_dir}), got: {al['alerts']}"
        a = flip_alerts[0]
        assert a["payload"]["from_direction"] == "down"
        assert a["payload"]["to_direction"] == new_dir
        assert a["read"] is False
        assert "_id" not in str(a)
    elif new_dir == "down":
        # No flip expected (same direction)
        assert len(flip_alerts) == 0, "Should not create flip alert when direction stayed 'down'"
    else:
        # 'flat' — current logic requires both prev & new in {up,down}, so no alert
        assert len(flip_alerts) == 0


# ---- Background task registered ----
def test_alerts_loop_task_registered():
    """We can't easily prove asyncio task is running over HTTP, but at minimum the
    POST /api/alerts/sync (which is what the loop calls) must work — already
    covered above. We additionally confirm backend boots cleanly."""
    r = requests.get(f"{API}/", timeout=10)
    assert r.status_code == 200


# ---- Regression: existing endpoints still work ----
def test_regression_quotes():
    r = requests.get(f"{API}/quotes", timeout=60)
    assert r.status_code == 200
    assert len(r.json()["quotes"]) > 0


def test_regression_exchange_rate():
    r = requests.get(f"{API}/exchange-rate", timeout=15)
    assert r.status_code == 200
    assert r.json()["rate"] > 0


def test_regression_watchlist_count_unchanged(mdb):
    r = requests.get(f"{API}/watchlist", timeout=15)
    assert r.status_code == 200
    tickers = r.json()["tickers"]
    # Should still have at least the 12 defaults
    assert len(tickers) >= 12


def test_regression_compare():
    r = requests.get(f"{API}/compare", params={"tickers": "NVDA,INTC"}, timeout=60)
    assert r.status_code == 200
    assert len(r.json()["series"]) == 2


# ---- Final teardown: clean alerts + ticker_state collections ----
def test_zz_final_cleanup(mdb):
    mdb.alerts.drop()
    mdb.ticker_state.drop()
    # Also clear seed prediction we inserted
    mdb.predictions.delete_many({"_pkey": {"$regex": "-seed$"}})
    assert mdb.alerts.count_documents({}) == 0
    assert mdb.ticker_state.count_documents({}) == 0
