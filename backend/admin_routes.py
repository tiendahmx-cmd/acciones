"""Admin-only endpoints: list/delete users with cascade."""
from fastapi import APIRouter, HTTPException, Depends

from deps import db, require_admin

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


@admin_router.get("/users")
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


@admin_router.delete("/users/{user_id}")
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
