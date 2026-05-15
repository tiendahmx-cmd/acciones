"""Iteration 4: Portfolio (lots, targets, aggregates) backend tests.

Validates POST/GET/DELETE /api/portfolio/lots, PUT/DELETE /api/portfolio/target,
GET /api/portfolio aggregation, and target/stop-loss cross alerts via
/api/alerts/sync. Uses pymongo to deterministically seed ticker_state.

Final cleanup drops position_lots, position_targets, alerts, ticker_state.
"""
import os
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
    mongo_url = db_name = None
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
    # Wipe portfolio collections at start of run for deterministic state
    db.position_lots.delete_many({})
    db.position_targets.delete_many({})
    db.alerts.delete_many({})
    db.ticker_state.delete_many({})
    yield db
    client.close()


# -------- POST /api/portfolio/lots --------
def test_add_lot_valid_minimal(mdb):
    payload = {"ticker": "nvda", "qty": 10, "buy_price_usd": 180.0}
    r = requests.post(f"{API}/portfolio/lots", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    for f in ["id", "ticker", "qty", "buy_price_usd", "buy_fx_rate", "buy_date", "created_at"]:
        assert f in d, f"missing {f}"
    assert d["ticker"] == "NVDA"
    assert d["qty"] == 10.0
    assert d["buy_price_usd"] == 180.0
    assert d["buy_fx_rate"] > 0  # filled from current rate
    # buy_date defaults to today (UTC YYYY-MM-DD)
    assert d["buy_date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert "_id" not in str(d)
    # Persisted
    doc = mdb.position_lots.find_one({"id": d["id"]})
    assert doc is not None and doc["ticker"] == "NVDA"


def test_add_lot_with_explicit_fx_and_date():
    payload = {"ticker": "NVDA", "qty": 5, "buy_price_usd": 210.0,
               "buy_fx_rate": 18.5, "buy_date": "2024-01-15"}
    r = requests.post(f"{API}/portfolio/lots", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["buy_fx_rate"] == 18.5
    assert d["buy_date"] == "2024-01-15"
    assert d["qty"] == 5.0


def test_add_lot_invalid_qty():
    r = requests.post(f"{API}/portfolio/lots",
                      json={"ticker": "NVDA", "qty": 0, "buy_price_usd": 100}, timeout=15)
    assert r.status_code == 400
    r2 = requests.post(f"{API}/portfolio/lots",
                       json={"ticker": "NVDA", "qty": -3, "buy_price_usd": 100}, timeout=15)
    assert r2.status_code == 400


def test_add_lot_invalid_price():
    r = requests.post(f"{API}/portfolio/lots",
                      json={"ticker": "NVDA", "qty": 5, "buy_price_usd": 0}, timeout=15)
    assert r.status_code == 400
    r2 = requests.post(f"{API}/portfolio/lots",
                      json={"ticker": "NVDA", "qty": 5, "buy_price_usd": -5}, timeout=15)
    assert r2.status_code == 400


def test_add_lot_invalid_ticker_format():
    # Empty / bad chars rejected by regex
    r = requests.post(f"{API}/portfolio/lots",
                      json={"ticker": "!!!", "qty": 5, "buy_price_usd": 100}, timeout=15)
    assert r.status_code == 400
    r2 = requests.post(f"{API}/portfolio/lots",
                      json={"ticker": "TOOLONGTICKERX", "qty": 5, "buy_price_usd": 100}, timeout=15)
    assert r2.status_code == 400


# -------- GET /api/portfolio/lots/{ticker} --------
def test_get_lots_for_ticker_ordered():
    r = requests.get(f"{API}/portfolio/lots/NVDA", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["ticker"] == "NVDA"
    lots = d["lots"]
    assert len(lots) >= 2
    # ordered by buy_date asc
    dates = [lt["buy_date"] for lt in lots]
    assert dates == sorted(dates)
    assert "_id" not in str(d)


# -------- DELETE /api/portfolio/lots/{lot_id} --------
def test_delete_lot_and_404(mdb):
    # Create a throwaway lot
    r = requests.post(f"{API}/portfolio/lots",
                     json={"ticker": "INTC", "qty": 1, "buy_price_usd": 25}, timeout=15)
    lot_id = r.json()["id"]
    d = requests.delete(f"{API}/portfolio/lots/{lot_id}", timeout=15)
    assert d.status_code == 200
    assert d.json()["deleted"] is True
    # gone
    assert mdb.position_lots.find_one({"id": lot_id}) is None
    # 404 on non-existent
    d2 = requests.delete(f"{API}/portfolio/lots/does-not-exist", timeout=15)
    assert d2.status_code == 404


# -------- PUT /api/portfolio/target/{ticker} --------
def test_set_target_both():
    r = requests.put(f"{API}/portfolio/target/NVDA",
                     json={"target_price": 250, "stop_loss_price": 170}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ticker"] == "NVDA"
    assert d["target_price"] == 250
    assert d["stop_loss_price"] == 170


def test_set_target_only_target_upserts():
    r = requests.put(f"{API}/portfolio/target/INTC", json={"target_price": 30}, timeout=15)
    assert r.status_code == 200
    assert r.json()["target_price"] == 30


def test_set_target_neither_400():
    r = requests.put(f"{API}/portfolio/target/INTC", json={}, timeout=15)
    assert r.status_code == 400


def test_set_target_negative_400():
    r = requests.put(f"{API}/portfolio/target/INTC", json={"target_price": -1}, timeout=15)
    assert r.status_code == 400
    r2 = requests.put(f"{API}/portfolio/target/INTC", json={"stop_loss_price": 0}, timeout=15)
    assert r2.status_code == 400


def test_delete_target_and_404():
    # INTC has target from prior test
    r = requests.delete(f"{API}/portfolio/target/INTC", timeout=15)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    r2 = requests.delete(f"{API}/portfolio/target/INTC", timeout=15)
    assert r2.status_code == 404


# -------- GET /api/portfolio aggregate --------
def test_portfolio_aggregate():
    """NVDA: lot1 (10@$180 fx=current), lot2 (5@$210 fx=18.5)
    Expected qty=15, total_cost_usd=10*180+5*210 = 2850, avg=190.0
    (Not 190.33 because both lots use same currency-weight equally for USD avg)
    """
    r = requests.get(f"{API}/portfolio", timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "positions" in d and "totals" in d and "mxn_rate" in d
    assert d["mxn_rate"] > 0
    # Find NVDA position
    nvda = next((p for p in d["positions"] if p["ticker"] == "NVDA"), None)
    assert nvda is not None, f"NVDA not in positions: {d['positions']}"
    assert nvda["qty"] == 15.0
    assert abs(nvda["total_cost_usd"] - 2850.0) < 0.01
    assert abs(nvda["avg_cost_usd"] - 190.0) < 0.01
    assert nvda["lots_count"] == 2
    assert nvda["target_price"] == 250
    assert nvda["stop_loss_price"] == 170
    # Current price + P&L computed
    assert nvda["current_price"] is not None and nvda["current_price"] > 0
    assert nvda["market_value_usd"] is not None
    assert nvda["pnl_usd"] is not None
    assert nvda["pnl_pct"] is not None
    assert nvda["market_value_mxn"] is not None
    assert nvda["pnl_mxn"] is not None
    # Totals match position sum (only NVDA exists)
    t = d["totals"]
    assert abs(t["cost_usd"] - nvda["total_cost_usd"]) < 0.01
    assert abs(t["value_usd"] - nvda["market_value_usd"]) < 0.01
    assert abs(t["pnl_usd"] - nvda["pnl_usd"]) < 0.01
    assert "_id" not in str(d)


def test_portfolio_empty(mdb):
    """Wipe lots, hit /api/portfolio, expect empty positions."""
    mdb.position_lots.delete_many({})
    mdb.position_targets.delete_many({})
    r = requests.get(f"{API}/portfolio", timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert d["positions"] == []
    t = d["totals"]
    for k in ["cost_usd", "value_usd", "pnl_usd", "pnl_pct", "cost_mxn", "value_mxn", "pnl_mxn"]:
        assert t[k] == 0
    assert d["mxn_rate"] > 0


# -------- Alerts: target + stop-loss crosses --------
def _seed_lot_and_target(mdb, ticker, target=None, stop=None):
    mdb.position_lots.insert_one({
        "id": f"seed-{ticker}",
        "ticker": ticker,
        "qty": 1.0,
        "buy_price_usd": 100.0,
        "buy_fx_rate": 18.0,
        "buy_date": "2024-01-01",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    update = {}
    if target is not None:
        update["target_price"] = target
    if stop is not None:
        update["stop_loss_price"] = stop
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    mdb.position_targets.update_one({"ticker": ticker}, {"$set": update}, upsert=True)


def test_target_hit_alert(mdb):
    """Seed lot + target so target sits between prev_price (last_price stored) and
    current quote, then trigger sync. Expects target_hits >= 1."""
    mdb.alerts.delete_many({})
    mdb.position_lots.delete_many({})
    mdb.position_targets.delete_many({})
    mdb.ticker_state.delete_many({})

    target_ticker = "NVDA"
    q = requests.get(f"{API}/quote/{target_ticker}", timeout=30).json()
    cur = q["quote"]["price"]
    assert cur and cur > 0

    # Pick target slightly BELOW current so prev<target<=current crosses
    target_price = round(cur * 0.95, 2)
    fake_prev = round(cur * 0.85, 2)  # well below target
    _seed_lot_and_target(mdb, target_ticker, target=target_price)
    mdb.ticker_state.update_one(
        {"ticker": target_ticker},
        {"$set": {"last_price": fake_prev, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    r = requests.post(f"{API}/alerts/sync", timeout=120)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "target_hits" in body and "price_moves" in body and "created" in body
    assert body["target_hits"] >= 1, (
        f"Expected target_hits>=1; got {body}. Likely root cause: _check_price_moves "
        f"runs first and overwrites ticker_state.last_price before _check_target_crosses reads it."
    )

    # Find alert
    al = requests.get(f"{API}/alerts", timeout=20).json()
    matched = [a for a in al["alerts"] if a["ticker"] == target_ticker and a["type"] == "target_hit"]
    assert len(matched) >= 1
    a = matched[0]
    p = a["payload"]
    assert "target_price" in p and "current_price" in p and "prev_price" in p
    assert p["target_price"] == target_price
    assert p["prev_price"] == fake_prev
    assert "_id" not in str(al)


def test_stop_loss_hit_alert(mdb):
    """Downward cross creates stop_loss_hit."""
    mdb.alerts.delete_many({})
    mdb.position_lots.delete_many({})
    mdb.position_targets.delete_many({})
    mdb.ticker_state.delete_many({})

    sym = "INTC"
    q = requests.get(f"{API}/quote/{sym}", timeout=30).json()
    cur = q["quote"]["price"]
    assert cur and cur > 0

    stop = round(cur * 1.05, 2)        # stop just above current → crossed downward
    fake_prev = round(cur * 1.15, 2)   # prev > stop
    _seed_lot_and_target(mdb, sym, stop=stop)
    mdb.ticker_state.update_one(
        {"ticker": sym},
        {"$set": {"last_price": fake_prev, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    r = requests.post(f"{API}/alerts/sync", timeout=120)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_hits"] >= 1, f"Expected stop-loss alert; got {body}"

    al = requests.get(f"{API}/alerts", timeout=20).json()
    matched = [a for a in al["alerts"] if a["ticker"] == sym and a["type"] == "stop_loss_hit"]
    assert len(matched) >= 1
    p = matched[0]["payload"]
    assert "stop_loss_price" in p and "current_price" in p and "prev_price" in p
    assert p["stop_loss_price"] == stop


def test_target_alert_skipped_without_lot(mdb):
    """Target set but no lot → no target_hit emitted."""
    mdb.alerts.delete_many({})
    mdb.position_lots.delete_many({})
    mdb.position_targets.delete_many({})
    mdb.ticker_state.delete_many({})

    sym = "QCOM"
    q = requests.get(f"{API}/quote/{sym}", timeout=30).json()
    cur = q["quote"]["price"]
    target_price = round(cur * 0.95, 2)
    fake_prev = round(cur * 0.85, 2)

    # only target, no lot
    mdb.position_targets.update_one(
        {"ticker": sym},
        {"$set": {"target_price": target_price,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    mdb.ticker_state.update_one(
        {"ticker": sym},
        {"$set": {"last_price": fake_prev}},
        upsert=True,
    )

    r = requests.post(f"{API}/alerts/sync", timeout=120)
    assert r.status_code == 200
    body = r.json()
    al = requests.get(f"{API}/alerts", timeout=20).json()
    target_hits = [a for a in al["alerts"] if a["ticker"] == sym and a["type"] == "target_hit"]
    assert len(target_hits) == 0, "Should not create target_hit alert without a lot"


def test_target_alert_cooldown(mdb):
    """Two consecutive syncs must not duplicate target_hit (6h cooldown)."""
    mdb.alerts.delete_many({})
    mdb.position_lots.delete_many({})
    mdb.position_targets.delete_many({})
    mdb.ticker_state.delete_many({})

    sym = "NVDA"
    q = requests.get(f"{API}/quote/{sym}", timeout=30).json()
    cur = q["quote"]["price"]
    target_price = round(cur * 0.95, 2)
    fake_prev = round(cur * 0.85, 2)

    _seed_lot_and_target(mdb, sym, target=target_price)
    mdb.ticker_state.update_one(
        {"ticker": sym},
        {"$set": {"last_price": fake_prev}},
        upsert=True,
    )

    r1 = requests.post(f"{API}/alerts/sync", timeout=120).json()
    first_hits = r1.get("target_hits", 0)

    # reset prev_price below target again to simulate "another cross"
    mdb.ticker_state.update_one(
        {"ticker": sym},
        {"$set": {"last_price": fake_prev}},
        upsert=True,
    )

    r2 = requests.post(f"{API}/alerts/sync", timeout=120).json()
    second_hits = r2.get("target_hits", 0)

    assert first_hits >= 1, f"First sync should fire target hit: {r1}"
    assert second_hits == 0, f"Cooldown violated: second sync produced {second_hits} target hits"


# -------- Regression --------
def test_regression_quotes():
    r = requests.get(f"{API}/quotes", timeout=60)
    assert r.status_code == 200
    assert len(r.json()["quotes"]) > 0


def test_regression_exchange_rate():
    r = requests.get(f"{API}/exchange-rate", timeout=15)
    assert r.status_code == 200
    assert r.json()["rate"] > 0


def test_regression_watchlist():
    r = requests.get(f"{API}/watchlist", timeout=15)
    assert r.status_code == 200
    assert len(r.json()["tickers"]) >= 12


def test_regression_compare():
    r = requests.get(f"{API}/compare", params={"tickers": "NVDA,INTC"}, timeout=60)
    assert r.status_code == 200
    assert len(r.json()["series"]) == 2


def test_regression_alerts_endpoint():
    r = requests.get(f"{API}/alerts", timeout=15)
    assert r.status_code == 200
    assert "alerts" in r.json()


# -------- Final cleanup --------
def test_zz_final_cleanup(mdb):
    mdb.position_lots.drop()
    mdb.position_targets.drop()
    mdb.alerts.drop()
    mdb.ticker_state.drop()
    assert mdb.position_lots.count_documents({}) == 0
    assert mdb.position_targets.count_documents({}) == 0
    assert mdb.alerts.count_documents({}) == 0
    assert mdb.ticker_state.count_documents({}) == 0
