"""Iteration 6: Closed-trades (sell) backend tests.

Covers POST /api/portfolio/sell (FIFO/LIFO/SPECIFIC + partial/full lot),
GET /api/portfolio/trades (with summary), GET /api/portfolio/trades/equity-curve,
DELETE /api/portfolio/trades/{id}, plus regression of prior endpoints.
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
    db.position_lots.delete_many({})
    db.position_targets.delete_many({})
    db.closed_trades.delete_many({})
    db.alerts.delete_many({})
    db.ticker_state.delete_many({})
    yield db
    client.close()


def _seed_two_nvda_lots(mdb):
    """10@180 dated 2026-01-01, 5@210 dated 2026-03-01."""
    mdb.position_lots.delete_many({"ticker": "NVDA"})
    mdb.position_lots.insert_many([
        {"id": "lot-old", "ticker": "NVDA", "qty": 10.0, "buy_price_usd": 180.0,
         "buy_fx_rate": 18.0, "buy_date": "2026-01-01",
         "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": "lot-new", "ticker": "NVDA", "qty": 5.0, "buy_price_usd": 210.0,
         "buy_fx_rate": 19.0, "buy_date": "2026-03-01",
         "created_at": datetime.now(timezone.utc).isoformat()},
    ])


# ---------- POST /api/portfolio/sell — FIFO ----------
def test_sell_fifo(mdb):
    _seed_two_nvda_lots(mdb)
    mdb.closed_trades.delete_many({})
    payload = {"ticker": "NVDA", "qty": 4, "sell_price_usd": 230,
               "sell_fx_rate": 20.0, "sell_date": "2026-04-01", "method": "FIFO"}
    r = requests.post(f"{API}/portfolio/sell", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "_id" not in d  # mongodb _id must not leak as top-level key
    assert d["ticker"] == "NVDA"
    assert d["method"] == "FIFO"
    assert d["qty_sold"] == 4.0
    assert len(d["allocations"]) == 1
    a = d["allocations"][0]
    assert a["lot_id"] == "lot-old"
    assert a["qty"] == 4.0
    assert a["buy_price_usd"] == 180.0
    # pnl = (230-180)*4 = 200
    assert abs(d["pnl_usd"] - 200.0) < 0.01
    assert a["days_held"] > 0
    assert d["avg_days_held"] > 0
    assert d["annualized_return_pct"] is not None
    # Lot mutation: old lot reduced to 6, new lot intact
    old = mdb.position_lots.find_one({"id": "lot-old"})
    new = mdb.position_lots.find_one({"id": "lot-new"})
    assert old and abs(old["qty"] - 6.0) < 1e-6
    assert new and abs(new["qty"] - 5.0) < 1e-6


def test_sell_lifo(mdb):
    _seed_two_nvda_lots(mdb)
    mdb.closed_trades.delete_many({})
    payload = {"ticker": "NVDA", "qty": 4, "sell_price_usd": 230,
               "sell_fx_rate": 20.0, "sell_date": "2026-04-01", "method": "LIFO"}
    r = requests.post(f"{API}/portfolio/sell", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "LIFO"
    assert len(d["allocations"]) == 1
    a = d["allocations"][0]
    assert a["lot_id"] == "lot-new"
    assert a["qty"] == 4.0
    # pnl = (230-210)*4 = 80
    assert abs(d["pnl_usd"] - 80.0) < 0.01
    new = mdb.position_lots.find_one({"id": "lot-new"})
    old = mdb.position_lots.find_one({"id": "lot-old"})
    assert new and abs(new["qty"] - 1.0) < 1e-6
    assert old and abs(old["qty"] - 10.0) < 1e-6


def test_sell_specific_custom_order(mdb):
    _seed_two_nvda_lots(mdb)
    mdb.closed_trades.delete_many({})
    # Order: new first then old; sell 7 → consume 5 from new (delete) + 2 from old
    payload = {"ticker": "NVDA", "qty": 7, "sell_price_usd": 220,
               "sell_fx_rate": 20.0, "sell_date": "2026-04-01",
               "method": "SPECIFIC", "lot_ids": ["lot-new", "lot-old"]}
    r = requests.post(f"{API}/portfolio/sell", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "SPECIFIC"
    assert len(d["allocations"]) == 2
    assert d["allocations"][0]["lot_id"] == "lot-new"
    assert d["allocations"][0]["qty"] == 5.0
    assert d["allocations"][1]["lot_id"] == "lot-old"
    assert d["allocations"][1]["qty"] == 2.0
    # new lot fully consumed → deleted, old lot reduced to 8
    assert mdb.position_lots.find_one({"id": "lot-new"}) is None
    old = mdb.position_lots.find_one({"id": "lot-old"})
    assert old and abs(old["qty"] - 8.0) < 1e-6


def test_sell_partial_lot_split(mdb):
    """1 lot qty=10, sell 4 → lot remains qty=6 (no orphan)."""
    mdb.position_lots.delete_many({"ticker": "TSLA"})
    mdb.position_lots.insert_one({
        "id": "tsla-lot", "ticker": "TSLA", "qty": 10.0, "buy_price_usd": 100.0,
        "buy_fx_rate": 18.0, "buy_date": "2026-01-15",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(f"{API}/portfolio/sell",
                      json={"ticker": "TSLA", "qty": 4, "sell_price_usd": 120,
                            "sell_fx_rate": 18.0, "sell_date": "2026-02-15"},
                      timeout=30)
    assert r.status_code == 200, r.text
    docs = list(mdb.position_lots.find({"ticker": "TSLA"}))
    assert len(docs) == 1
    assert docs[0]["id"] == "tsla-lot"
    assert abs(docs[0]["qty"] - 6.0) < 1e-6


def test_sell_full_consumption(mdb):
    mdb.position_lots.delete_many({"ticker": "AMZN"})
    mdb.position_lots.insert_one({
        "id": "amzn-lot", "ticker": "AMZN", "qty": 5.0, "buy_price_usd": 150.0,
        "buy_fx_rate": 18.0, "buy_date": "2026-01-15",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.post(f"{API}/portfolio/sell",
                      json={"ticker": "AMZN", "qty": 5, "sell_price_usd": 100,
                            "sell_fx_rate": 18.0, "sell_date": "2026-02-15"},
                      timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pnl_usd"] < 0  # loss
    assert mdb.position_lots.find_one({"id": "amzn-lot"}) is None


def test_sell_qty_exceeds_total(mdb):
    _seed_two_nvda_lots(mdb)
    r = requests.post(f"{API}/portfolio/sell",
                      json={"ticker": "NVDA", "qty": 100, "sell_price_usd": 230},
                      timeout=15)
    assert r.status_code == 400


def test_sell_invalid_qty_price_method(mdb):
    _seed_two_nvda_lots(mdb)
    r1 = requests.post(f"{API}/portfolio/sell",
                       json={"ticker": "NVDA", "qty": 0, "sell_price_usd": 230},
                       timeout=15)
    assert r1.status_code == 400
    r2 = requests.post(f"{API}/portfolio/sell",
                       json={"ticker": "NVDA", "qty": 1, "sell_price_usd": 0},
                       timeout=15)
    assert r2.status_code == 400
    r3 = requests.post(f"{API}/portfolio/sell",
                       json={"ticker": "NVDA", "qty": 1, "sell_price_usd": 230,
                             "method": "BOGUS"},
                       timeout=15)
    assert r3.status_code == 400


def test_sell_specific_validations(mdb):
    _seed_two_nvda_lots(mdb)
    # Missing lot_ids
    r1 = requests.post(f"{API}/portfolio/sell",
                       json={"ticker": "NVDA", "qty": 1, "sell_price_usd": 230,
                             "method": "SPECIFIC"}, timeout=15)
    assert r1.status_code == 400
    # Unknown lot id
    r2 = requests.post(f"{API}/portfolio/sell",
                       json={"ticker": "NVDA", "qty": 1, "sell_price_usd": 230,
                             "method": "SPECIFIC", "lot_ids": ["nope"]}, timeout=15)
    assert r2.status_code == 400


def test_sell_no_lots_404(mdb):
    mdb.position_lots.delete_many({"ticker": "ZZZZ"})
    r = requests.post(f"{API}/portfolio/sell",
                      json={"ticker": "ZZZZ", "qty": 1, "sell_price_usd": 50},
                      timeout=15)
    assert r.status_code == 404


# ---------- GET /api/portfolio/trades ----------
def test_list_trades_with_summary(mdb):
    """Seed deterministic trades and verify sort/summary."""
    mdb.closed_trades.delete_many({})
    mdb.closed_trades.insert_many([
        {"id": "t1", "ticker": "AAA", "sell_date": "2026-02-15",
         "pnl_usd": 100.0, "pnl_mxn": 1800.0, "cost_usd": 500.0,
         "qty_sold": 5, "method": "FIFO", "allocations": []},
        {"id": "t2", "ticker": "BBB", "sell_date": "2026-03-20",
         "pnl_usd": -40.0, "pnl_mxn": -720.0, "cost_usd": 300.0,
         "qty_sold": 3, "method": "FIFO", "allocations": []},
        {"id": "t3", "ticker": "CCC", "sell_date": "2026-01-10",
         "pnl_usd": 60.0, "pnl_mxn": 1080.0, "cost_usd": 200.0,
         "qty_sold": 2, "method": "FIFO", "allocations": []},
    ])
    r = requests.get(f"{API}/portfolio/trades", timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert "_id" not in d  # top-level mongo _id must not leak
    for t in d["trades"]:
        assert "_id" not in t
    trades = d["trades"]
    # sorted by sell_date desc
    assert [t["id"] for t in trades] == ["t2", "t1", "t3"]
    s = d["summary"]
    assert s["count"] == 3
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert abs(s["win_rate"] - 66.7) < 0.1
    assert abs(s["total_pnl_usd"] - 120.0) < 0.01
    assert abs(s["total_pnl_mxn"] - 2160.0) < 0.01
    # total_return_pct = 120/1000 *100 = 12.0
    assert abs(s["total_return_pct"] - 12.0) < 0.1


# ---------- GET /api/portfolio/trades/equity-curve ----------
def test_equity_curve(mdb):
    """Uses 3 trades seeded above (Jan, Feb, Mar 2026)."""
    r = requests.get(f"{API}/portfolio/trades/equity-curve", timeout=20)
    assert r.status_code == 200
    pts = r.json()["points"]
    months = [p["month"] for p in pts]
    assert months == sorted(months)  # ascending
    assert months == ["2026-01", "2026-02", "2026-03"]
    # Cumulative: 60, 60+100=160, 160-40=120
    assert abs(pts[0]["cumulative_usd"] - 60.0) < 0.01
    assert abs(pts[1]["cumulative_usd"] - 160.0) < 0.01
    assert abs(pts[2]["cumulative_usd"] - 120.0) < 0.01
    # Per-month pnl
    assert abs(pts[0]["pnl_usd"] - 60.0) < 0.01
    assert abs(pts[1]["pnl_usd"] - 100.0) < 0.01
    assert abs(pts[2]["pnl_usd"] - (-40.0)) < 0.01
    # MXN cumulative present
    for p in pts:
        assert "cumulative_mxn" in p and "pnl_mxn" in p


# ---------- DELETE /api/portfolio/trades/{id} ----------
def test_delete_trade(mdb):
    r = requests.delete(f"{API}/portfolio/trades/t1", timeout=15)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert mdb.closed_trades.find_one({"id": "t1"}) is None


def test_delete_trade_404():
    r = requests.delete(f"{API}/portfolio/trades/nope-xx", timeout=15)
    assert r.status_code == 404


# ---------- Regression sanity ----------
def test_regression_watchlist_defaults():
    r = requests.get(f"{API}/watchlist", timeout=15)
    assert r.status_code == 200
    assert len(r.json()["tickers"]) >= 12


def test_regression_exchange_rate():
    r = requests.get(f"{API}/exchange-rate", timeout=15)
    assert r.status_code == 200
    assert r.json()["rate"] > 0


def test_regression_portfolio_endpoint():
    r = requests.get(f"{API}/portfolio", timeout=60)
    assert r.status_code == 200
    assert "positions" in r.json()


# ---------- Final cleanup ----------
def test_zz_final_cleanup(mdb):
    mdb.position_lots.drop()
    mdb.position_targets.drop()
    mdb.closed_trades.drop()
    mdb.alerts.drop()
    mdb.ticker_state.drop()
    assert mdb.position_lots.count_documents({}) == 0
    assert mdb.closed_trades.count_documents({}) == 0
