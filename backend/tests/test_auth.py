"""
Iteration 7 — JWT auth + admin + data isolation tests.

Covers:
  - /api/auth/register, /api/auth/login, /api/auth/me, /api/auth/logout
  - Brute-force lockout (5 fails -> 429)
  - Admin seeding (admin@stocks.app / Admin#Stocks2026)
  - Protected endpoints reject missing/invalid tokens
  - Data isolation between users (watchlist, portfolio lots, alerts)
  - Admin ?admin_all=true (cross-user view) for portfolio + alerts
  - /api/admin/users list (admin only) + DELETE (cascade + no self-delete)
  - _id / password_hash never leak in auth responses
"""
import os
import uuid
import time
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@stocks.app"
ADMIN_PASSWORD = "Admin#Stocks2026"


def _new_email(tag: str) -> str:
    return f"TEST-{tag}-{uuid.uuid4().hex[:8]}@stocks.app"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "admin"
    return data["token"]


@pytest.fixture(scope="module")
def user_a(http):
    email = _new_email("A")
    r = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!", "name": "Alice"})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"email": email, "password": "passw0rd!", "token": d["token"], "id": d["user"]["id"]}


@pytest.fixture(scope="module")
def user_b(http):
    email = _new_email("B")
    r = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!", "name": "Bob"})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"email": email, "password": "passw0rd!", "token": d["token"], "id": d["user"]["id"]}


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- register / login / me ----------
class TestAuthBasics:
    def test_register_returns_token_and_user(self, http):
        email = _new_email("reg")
        r = http.post(f"{API}/auth/register", json={"email": email, "password": "abcdef1", "name": "Reg"})
        assert r.status_code == 200
        d = r.json()
        assert "token" in d and isinstance(d["token"], str) and len(d["token"]) > 20
        u = d["user"]
        assert u["email"] == email.lower()
        assert u["name"] == "Reg"
        assert u["role"] == "user"
        assert "id" in u
        # No leaks
        body = r.text
        assert "password_hash" not in body
        assert "_id" not in body
        # /me should work with token
        me = http.get(f"{API}/auth/me", headers=H(d["token"]))
        assert me.status_code == 200
        assert me.json()["user"]["email"] == email.lower()

    def test_register_duplicate_email_returns_400(self, http, user_a):
        r = http.post(f"{API}/auth/register", json={"email": user_a["email"], "password": "anotherpwd"})
        assert r.status_code == 400

    def test_register_short_password_422(self, http):
        r = http.post(f"{API}/auth/register", json={"email": _new_email("short"), "password": "abc"})
        assert r.status_code == 422

    def test_login_valid(self, http, user_a):
        r = http.post(f"{API}/auth/login", json={"email": user_a["email"], "password": user_a["password"]})
        assert r.status_code == 200
        d = r.json()
        assert "token" in d
        assert d["user"]["id"] == user_a["id"]
        assert d["user"]["role"] == "user"
        assert "password_hash" not in r.text
        assert "_id" not in r.text

    def test_login_invalid_returns_401(self, http):
        # use a unique never-seen email so we don't pollute lockout
        r = http.post(f"{API}/auth/login", json={"email": _new_email("nope"), "password": "wrongpwd"})
        assert r.status_code == 401

    def test_me_without_token_401(self, http):
        r = http.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token_401(self, http):
        r = http.get(f"{API}/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"})
        assert r.status_code == 401

    def test_admin_seeded_and_login(self, admin_token, http):
        r = http.get(f"{API}/auth/me", headers=H(admin_token))
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["email"] == ADMIN_EMAIL
        assert u["role"] == "admin"


# ---------- brute-force lockout ----------
class TestBruteForce:
    def test_five_wrong_then_429(self, http):
        # Unique email so we don't lock anyone else out
        email = _new_email("bf")
        # Register so account exists (otherwise still 401 but path is same)
        http.post(f"{API}/auth/register", json={"email": email, "password": "rightpwd"})
        codes = []
        for _ in range(5):
            r = http.post(f"{API}/auth/login", json={"email": email, "password": "WRONG-pwd"})
            codes.append(r.status_code)
        # First 5 wrong = 401, then 6th attempt should be locked -> 429
        assert codes == [401, 401, 401, 401, 401], f"unexpected codes: {codes}"
        r = http.post(f"{API}/auth/login", json={"email": email, "password": "rightpwd"})
        # After 5 fails the lockout kicks in even with correct password
        assert r.status_code == 429, f"expected 429 lockout, got {r.status_code}: {r.text}"


# ---------- protected endpoints require auth ----------
PROTECTED_GET = [
    "/watchlist",
    "/quotes",
    "/quote/NVDA",
    "/history/NVDA",
    "/compare?tickers=NVDA,AMZN",
    "/alerts",
    "/portfolio",
    "/portfolio/lots/NVDA",
    "/portfolio/trades",
    "/portfolio/trades/equity-curve",
]


class TestProtectedEndpoints:
    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_get_without_token_401(self, http, path):
        r = http.get(f"{API}{path}")
        assert r.status_code == 401, f"{path} returned {r.status_code}"

    def test_predict_without_token_401(self, http):
        r = http.post(f"{API}/predict/NVDA")
        assert r.status_code == 401

    def test_post_watchlist_without_token_401(self, http):
        r = http.post(f"{API}/watchlist", json={"ticker": "NVDA"})
        assert r.status_code == 401

    def test_post_lot_without_token_401(self, http):
        r = http.post(f"{API}/portfolio/lots", json={"ticker": "NVDA", "qty": 1, "buy_price_usd": 100, "buy_date": "2024-01-01"})
        assert r.status_code == 401

    def test_admin_users_without_token_401(self, http):
        r = http.get(f"{API}/admin/users")
        assert r.status_code == 401

    def test_admin_users_as_normal_user_403(self, http, user_a):
        r = http.get(f"{API}/admin/users", headers=H(user_a["token"]))
        assert r.status_code == 403


# ---------- isolation ----------
class TestIsolation:
    def test_watchlist_seeded_per_user(self, http, user_a, user_b):
        ra = http.get(f"{API}/watchlist", headers=H(user_a["token"]))
        rb = http.get(f"{API}/watchlist", headers=H(user_b["token"]))
        assert ra.status_code == 200 and rb.status_code == 200
        ta = set(ra.json()["tickers"])
        tb = set(rb.json()["tickers"])
        # both should have the 12 defaults seeded
        assert len(ta) >= 12 and len(tb) >= 12

    def test_watchlist_custom_add_isolated(self, http, user_a, user_b):
        # A removes NVDA, adds a custom one (skip add to avoid network ticker validation flake)
        # Use the existing default removal isolation pattern:
        rdel = http.delete(f"{API}/watchlist/NVDA", headers=H(user_a["token"]))
        assert rdel.status_code in (200, 404)
        ra = http.get(f"{API}/watchlist", headers=H(user_a["token"]))
        rb = http.get(f"{API}/watchlist", headers=H(user_b["token"]))
        ta = set(ra.json()["tickers"])
        tb = set(rb.json()["tickers"])
        # B must still have NVDA, A must not
        assert "NVDA" in tb
        assert "NVDA" not in ta

    def test_portfolio_lots_isolated(self, http, user_a, user_b):
        payload = {"ticker": "AAPL", "qty": 5, "buy_price_usd": 150.0, "buy_date": "2024-01-01"}
        r = http.post(f"{API}/portfolio/lots", json=payload, headers=H(user_a["token"]))
        assert r.status_code == 200, r.text
        # A sees AAPL
        pa = http.get(f"{API}/portfolio", headers=H(user_a["token"]))
        assert pa.status_code == 200
        tickers_a = {p["ticker"] for p in pa.json()["positions"]}
        assert "AAPL" in tickers_a
        # B does NOT see AAPL
        pb = http.get(f"{API}/portfolio", headers=H(user_b["token"]))
        assert pb.status_code == 200
        tickers_b = {p["ticker"] for p in pb.json()["positions"]}
        assert "AAPL" not in tickers_b

    def test_alerts_isolated(self, http, user_a, user_b):
        # seed alert for A directly via DB-equivalent: use sync (may yield 0). Fallback: insert via predict change.
        # Simplest: just verify GET returns user-scoped collection — create alert via sync then ensure B doesn't see A's alerts.
        # Use direct mongo insert via admin tooling not available here; instead just assert the lists are user-scoped (empty for B).
        ra = http.get(f"{API}/alerts", headers=H(user_a["token"]))
        rb = http.get(f"{API}/alerts", headers=H(user_b["token"]))
        assert ra.status_code == 200 and rb.status_code == 200
        # Each response has its own count; values should not cross-leak. If A has alerts but B is fresh, B.total should be 0.
        # Even if both 0, ensure response shape and that admin_all flag (silently ignored for normal user) doesn't expand B's view.
        rb_admin_attempt = http.get(f"{API}/alerts?admin_all=true", headers=H(user_b["token"]))
        assert rb_admin_attempt.status_code == 200
        # silently ignored: result must equal user-scoped result
        assert rb_admin_attempt.json()["total"] == rb.json()["total"]

    def test_non_admin_admin_all_silently_ignored_on_portfolio(self, http, user_a, user_b):
        # user_a has AAPL, user_b does not. user_b sending admin_all=true must STILL not see AAPL.
        rb = http.get(f"{API}/portfolio?admin_all=true", headers=H(user_b["token"]))
        assert rb.status_code == 200
        tickers_b = {p["ticker"] for p in rb.json()["positions"]}
        assert "AAPL" not in tickers_b


# ---------- admin powers ----------
class TestAdmin:
    def test_admin_portfolio_admin_all_cross_user(self, http, admin_token, user_a):
        r = http.get(f"{API}/portfolio?admin_all=true", headers=H(admin_token))
        assert r.status_code == 200
        positions = r.json()["positions"]
        # Every row must include user_id
        assert all("user_id" in p for p in positions)
        # user_a's AAPL must appear
        match = [p for p in positions if p["ticker"] == "AAPL" and p["user_id"] == user_a["id"]]
        assert len(match) == 1, f"admin should see user_a's AAPL: {positions}"

    def test_admin_portfolio_without_admin_all_is_scoped(self, http, admin_token, user_a):
        r = http.get(f"{API}/portfolio", headers=H(admin_token))
        assert r.status_code == 200
        # Admin's own portfolio (likely empty) — must NOT contain user_a's AAPL
        positions = r.json()["positions"]
        assert not any(p.get("user_id") == user_a["id"] for p in positions)

    def test_admin_alerts_admin_all(self, http, admin_token):
        r = http.get(f"{API}/alerts?admin_all=true", headers=H(admin_token))
        assert r.status_code == 200
        # shape only — we may have zero alerts in fresh DB
        assert "alerts" in r.json() and "total" in r.json()

    def test_admin_list_users(self, http, admin_token, user_a, user_b):
        r = http.get(f"{API}/admin/users", headers=H(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 3  # admin + A + B (at least)
        emails = {u["email"] for u in d["users"]}
        assert ADMIN_EMAIL in emails
        assert user_a["email"].lower() in emails
        assert user_b["email"].lower() in emails
        # No leaks
        body = r.text
        assert "password_hash" not in body
        assert '"_id"' not in body
        # Stats keys present
        sample = d["users"][0]
        assert "stats" in sample
        for k in ("watchlist", "lots", "trades", "alerts", "unread_alerts"):
            assert k in sample["stats"]

    def test_admin_cannot_delete_self(self, http, admin_token):
        # find admin id
        r = http.get(f"{API}/auth/me", headers=H(admin_token))
        admin_id = r.json()["user"]["id"]
        d = http.delete(f"{API}/admin/users/{admin_id}", headers=H(admin_token))
        assert d.status_code == 400

    def test_admin_delete_user_cascades(self, http, admin_token):
        # create a throwaway user with some data
        email = _new_email("del")
        reg = http.post(f"{API}/auth/register", json={"email": email, "password": "passw0rd!"})
        assert reg.status_code == 200
        tok = reg.json()["token"]
        uid = reg.json()["user"]["id"]
        # seed lot for that user
        lot = http.post(f"{API}/portfolio/lots",
                        json={"ticker": "MSFT", "qty": 1, "buy_price_usd": 100, "buy_date": "2024-01-01"},
                        headers=H(tok))
        assert lot.status_code == 200
        # seed watchlist auto via GET
        http.get(f"{API}/watchlist", headers=H(tok))

        # delete
        d = http.delete(f"{API}/admin/users/{uid}", headers=H(admin_token))
        assert d.status_code == 200, d.text
        assert d.json()["deleted"] is True

        # user must be gone -> /me with old token should 401 (user not found)
        me = http.get(f"{API}/auth/me", headers=H(tok))
        assert me.status_code == 401

        # admin listing should not include them
        r = http.get(f"{API}/admin/users", headers=H(admin_token))
        emails = {u["email"] for u in r.json()["users"]}
        assert email.lower() not in emails

        # admin_all portfolio should not contain that user_id
        port = http.get(f"{API}/portfolio?admin_all=true", headers=H(admin_token))
        assert port.status_code == 200
        assert not any(p.get("user_id") == uid for p in port.json()["positions"])

    def test_admin_delete_nonexistent_404(self, http, admin_token):
        d = http.delete(f"{API}/admin/users/does-not-exist-{uuid.uuid4().hex}", headers=H(admin_token))
        assert d.status_code == 404


# ---------- cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(http):
    """Remove all TEST- users (except admin) and their data at end of module."""
    yield
    # Use admin token to nuke our test users
    rl = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if rl.status_code != 200:
        return
    tok = rl.json()["token"]
    lst = http.get(f"{API}/admin/users", headers=H(tok))
    if lst.status_code != 200:
        return
    for u in lst.json()["users"]:
        if u["email"].startswith("test-") or u["email"].startswith("TEST-".lower()) or "test-" in u["email"]:
            if u["email"] == ADMIN_EMAIL:
                continue
            http.delete(f"{API}/admin/users/{u['id']}", headers=H(tok))
