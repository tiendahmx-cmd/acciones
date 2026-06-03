"""Authentication routes: register, login, logout, me."""
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request

from deps import (
    db,
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    RegisterRequest,
    LoginRequest,
)

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register")
async def register(req: RegisterRequest, request: Request):
    email = req.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)

    # Per-IP throttling: max 10 registrations / hour
    rl_key = f"reg:{ip}"
    rl = await db.login_attempts.find_one({"identifier": rl_key})
    if rl:
        window_start = datetime.fromisoformat(rl.get("window_start", now.isoformat()))
        if (now - window_start).total_seconds() < 3600 and rl.get("count", 0) >= 10:
            raise HTTPException(status_code=429, detail="Demasiados registros desde tu IP. Intenta en una hora.")
        if (now - window_start).total_seconds() >= 3600:
            await db.login_attempts.update_one(
                {"identifier": rl_key}, {"$set": {"count": 0, "window_start": now.isoformat()}}
            )

    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Ese email ya está registrado")

    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": email,
        "name": req.name or email.split("@")[0],
        "password_hash": hash_password(req.password),
        "role": "user",
        "created_at": now.isoformat(),
    }
    await db.users.insert_one(doc)
    await db.login_attempts.update_one(
        {"identifier": rl_key},
        {"$inc": {"count": 1}, "$setOnInsert": {"window_start": now.isoformat()}},
        upsert=True,
    )
    token = create_access_token(user_id, email)
    return {
        "token": token,
        "user": {"id": user_id, "email": email, "name": doc["name"], "role": "user"},
    }


@auth_router.post("/login")
async def login(req: LoginRequest, request: Request):
    email = req.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    ip_key = f"{ip}:{email}"
    email_key = f"email:{email}"
    now = datetime.now(timezone.utc)

    # Two parallel lockouts: per (IP,email) AND per email globally.
    for key, threshold in ((ip_key, 5), (email_key, 10)):
        att = await db.login_attempts.find_one({"identifier": key})
        if att:
            locked_until = att.get("locked_until")
            if locked_until and datetime.fromisoformat(locked_until) > now:
                raise HTTPException(status_code=429, detail="Demasiados intentos. Intenta en unos minutos.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user["password_hash"]):
        for key, threshold in ((ip_key, 5), (email_key, 10)):
            att = await db.login_attempts.find_one({"identifier": key}) or {}
            fails = att.get("fails", 0) + 1
            update = {"identifier": key, "fails": fails, "last_at": now.isoformat()}
            if fails >= threshold:
                update["locked_until"] = (now + timedelta(minutes=15)).isoformat()
                update["fails"] = 0
            await db.login_attempts.update_one({"identifier": key}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    await db.login_attempts.delete_one({"identifier": ip_key})
    await db.login_attempts.delete_one({"identifier": email_key})
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
