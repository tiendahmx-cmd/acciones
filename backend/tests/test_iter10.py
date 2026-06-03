"""
Iteration 10 — hardening + CSV export + module refactor.

NEW Tests:
  - /api/auth/register per-IP rate limit (10/hour)
  - /api/auth/login per-email global lockout (10 fails)
  - /api/portfolio/trades/export.csv (auth required, CSV headers, body filter, admin_all)
  - Module imports OK (server boots, /api/ root responds)
"""
import os
import uuid
import csv
import io
import pytest
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Direct DB access for setup/cleanup (rate-limit table manipulation)
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@stocks.app"
ADMIN_PASSWORD = "KOsso8032#$+"

_mongo = MongoClient(os.environ["MONGO_URL"])
_db = _mongo[os.environ["DB_NAME"]]


def _new_email(tag: str) -> str:
    return f"TEST-iter10-{tag}-{uuid.uuid4().hex[:8]}@stocks.app"


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def user_token(http):
    email = _new_email("user")
    # Pre-clear register rate limit
    _db.login_attempts.delete_many({"identifier": {"$regex": "^reg:"}})
    r = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!", "name": "U"})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"email": email, "id": d["user"]["id"], "token": d["token"]}


# ---------- Module imports / boot ----------
class TestModuleImports:
    def test_backend_boots_root(self, http):
        r = http.get(f"{API}/")
        assert r.status_code == 200
        assert "message" in r.json()

    def test_auth_router_mounted(self, http):
        # /me without token → 401, confirms route exists
        r = http.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_admin_router_mounted(self, http):
        # /admin/users without token → 401
        r = http.get(f"{API}/admin/users")
        assert r.status_code == 401


# ---------- Register per-IP rate limit ----------
class TestRegisterRateLimit:
    def test_register_eleventh_returns_429(self, http):
        # Clear any existing reg rate-limit rows
        _db.login_attempts.delete_many({"identifier": {"$regex": "^reg:"}})

        successes = 0
        last_status = None
        last_text = ""
        # 10 should succeed, 11th should 429
        for i in range(11):
            email = _new_email(f"rl{i}")
            r = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!"})
            last_status = r.status_code
            last_text = r.text
            if r.status_code == 200:
                successes += 1
            elif r.status_code == 429:
                break

        assert successes == 10, f"expected 10 successes before 429, got {successes} (last={last_status} {last_text[:200]})"
        assert last_status == 429, f"expected 429 on 11th, got {last_status}: {last_text[:200]}"

        # 12th attempt also still 429
        r = http.post(f"{API}/auth/register", json={"email": _new_email("rl12"), "password": "passw0rd!"})
        assert r.status_code == 429, f"expected continued 429, got {r.status_code}"

        # Cleanup so other tests aren't blocked
        _db.login_attempts.delete_many({"identifier": {"$regex": "^reg:"}})


# ---------- Per-email global lockout ----------
class TestPerEmailLockout:
    def test_per_email_lockout_threshold_10(self, http):
        """Pre-seed email_key with fails=9; one more wrong attempt should push it to 10 and lock."""
        email = _new_email("email-lock")
        # register the account (uses a reg slot — ok, cleanup at end)
        _db.login_attempts.delete_many({"identifier": {"$regex": "^reg:"}})
        r = http.post(f"{API}/auth/register", json={"email": email, "password": "rightpwd"})
        assert r.status_code == 200, r.text

        email_norm = email.lower()
        email_key = f"email:{email_norm}"
        # Clean any prior state for this email
        _db.login_attempts.delete_many({"identifier": email_key})

        # Pre-seed fails=9 (one short of lockout threshold)
        _db.login_attempts.insert_one({
            "identifier": email_key,
            "fails": 9,
            "last_at": datetime.now(timezone.utc).isoformat(),
        })

        # Single wrong attempt should bring email fails to 10 → set locked_until
        r = http.post(f"{API}/auth/login", json={"email": email, "password": "WRONG-pwd"})
        # First wrong attempt: returns 401 (lockout set on this attempt, not yet enforced)
        assert r.status_code == 401, f"expected 401 first wrong attempt, got {r.status_code}: {r.text}"

        # Confirm email key now has locked_until
        rec = _db.login_attempts.find_one({"identifier": email_key})
        assert rec is not None and rec.get("locked_until"), f"expected lock on email key, got {rec}"

        # Next attempt — even with correct pwd — must be blocked by email lockout → 429
        r = http.post(f"{API}/auth/login", json={"email": email, "password": "rightpwd"})
        assert r.status_code == 429, f"expected 429 after email lockout, got {r.status_code}: {r.text}"

        # Cleanup so we don't lock manual testing
        _db.login_attempts.delete_many({"identifier": email_key})
        ip_keys = _db.login_attempts.find({"identifier": {"$regex": f":{email_norm}$"}})
        for k in ip_keys:
            _db.login_attempts.delete_one({"_id": k["_id"]})


# ---------- CSV export ----------
class TestCsvExport:
    EXPECTED_HEADERS = [
        "sell_date", "ticker", "method", "qty_sold",
        "sell_price_usd", "sell_fx_rate", "proceeds_usd", "proceeds_mxn",
        "cost_usd", "cost_mxn", "pnl_usd", "pnl_mxn",
        "return_pct", "avg_days_held", "annualized_return_pct",
        "lots_consumed",
    ]

    def test_csv_export_requires_auth(self, http):
        r = http.get(f"{API}/portfolio/trades/export.csv")
        assert r.status_code == 401

    def test_csv_export_headers_and_content_type(self, http, user_token):
        r = http.get(f"{API}/portfolio/trades/export.csv", headers=H(user_token["token"]))
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "").lower()
        assert "text/csv" in ct, f"expected text/csv, got {ct}"
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower(), f"expected attachment content-disposition, got {cd}"
        assert "filename" in cd.lower()
        # Header row check
        body = r.text
        reader = csv.reader(io.StringIO(body))
        header = next(reader)
        assert header == self.EXPECTED_HEADERS, f"unexpected CSV header: {header}"

    def test_csv_export_user_scoped(self, http, user_token):
        """Create a lot+sell for user, verify it appears in their CSV."""
        # add lot
        r = http.post(
            f"{API}/portfolio/lots",
            json={"ticker": "AAPL", "qty": 3, "buy_price_usd": 100.0, "buy_date": "2024-01-15"},
            headers=H(user_token["token"]),
        )
        assert r.status_code == 200, r.text
        # sell
        r = http.post(
            f"{API}/portfolio/sell",
            json={"ticker": "AAPL", "qty": 3, "sell_price_usd": 150.0, "sell_date": "2024-06-15", "method": "FIFO"},
            headers=H(user_token["token"]),
        )
        assert r.status_code == 200, r.text

        # fetch csv
        r = http.get(f"{API}/portfolio/trades/export.csv", headers=H(user_token["token"]))
        assert r.status_code == 200
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)
        aapl = [row for row in rows if row.get("ticker") == "AAPL"]
        assert len(aapl) >= 1, f"expected AAPL trade in CSV, got rows: {rows}"
        # verify numeric values are present
        assert aapl[0]["qty_sold"]
        assert aapl[0]["sell_price_usd"]
        assert aapl[0]["pnl_usd"]
        assert aapl[0]["method"] == "FIFO"

    def test_csv_export_user_does_not_see_other_users_trades(self, http, user_token):
        """Register a second user, confirm they don't see user_token's AAPL trade."""
        _db.login_attempts.delete_many({"identifier": {"$regex": "^reg:"}})
        email = _new_email("other")
        r = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!"})
        assert r.status_code == 200, r.text
        other_token = r.json()["token"]
        r = http.get(f"{API}/portfolio/trades/export.csv", headers=H(other_token))
        assert r.status_code == 200
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)
        # the other user has no trades → only header row
        assert len(rows) == 0, f"other user should not see anyone's trades, got {len(rows)}"

    def test_csv_export_admin_all(self, http, admin_token, user_token):
        """Admin with ?admin_all=true should see user_token's AAPL trade."""
        r = http.get(f"{API}/portfolio/trades/export.csv?admin_all=true", headers=H(admin_token))
        assert r.status_code == 200
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)
        aapl = [row for row in rows if row.get("ticker") == "AAPL"]
        assert len(aapl) >= 1, f"admin admin_all should see AAPL trade across users, got {rows}"

    def test_csv_export_admin_without_admin_all_is_scoped(self, http, admin_token):
        """Admin without admin_all sees only own trades (likely none)."""
        r = http.get(f"{API}/portfolio/trades/export.csv", headers=H(admin_token))
        assert r.status_code == 200
        # Just ensure it returned CSV; content may be header-only
        assert "sell_date" in r.text.split("\n")[0]


# ---------- Final cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(http):
    yield
    # Clean rate-limit / lockout state so manual testing isn't blocked
    _db.login_attempts.drop()
    # Best-effort: delete TEST-iter10 users via admin
    rl = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if rl.status_code == 200:
        tok = rl.json()["token"]
        lst = http.get(f"{API}/admin/users", headers=H(tok))
        if lst.status_code == 200:
            for u in lst.json()["users"]:
                if "iter10" in u["email"].lower() or u["email"].startswith("test-iter10"):
                    http.delete(f"{API}/admin/users/{u['id']}", headers=H(tok))
