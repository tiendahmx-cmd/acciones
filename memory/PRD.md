# Stock Tracker — NASDAQ/NYSE Dashboard

## Original Problem Statement
Web app with elegant dark UX/UI displaying real-time NASDAQ/NYSE quotes (INTC, SMCI, VIST, DELL, QCOM, NTR, MELI, BABA, TQQQ, NVDA, WDC, SLV). Show price, % change, open, high, MXN equivalent. AI-powered next-day price predictions and relevant news per stock. Customizable watchlist (add/remove). Click stock opens side panel with prediction + news.

## Architecture
- **Backend**: FastAPI + MongoDB (Motor). Endpoints under `/api/`.
- **Frontend**: React 19 + Tailwind + Shadcn UI + Phosphor Icons. Dark "Control Room" theme.
- **Stock data**: Yahoo Finance via `yfinance` (no key).
- **FX**: frankfurter.dev → open.er-api.com fallback. 10-min server cache.
- **AI**: Gemini 3 Flash via `emergentintegrations` (Emergent LLM Key).
- **No auth** — single global watchlist persisted in MongoDB.

## User Personas
- Retail investor in Mexico tracking US equities with MXN reference.

## Core Requirements
- Real-time quotes (price, change, %, open, high, low, prev close, MXN).
- USD/MXN displayed in header, applied to each stock.
- Add/remove tickers (validation against Yahoo).
- AI prediction (next-day price + direction + confidence + rationale) and 3 news headlines.
- Auto-refresh every 60s, manual refresh button.

## Implemented (2026-02)
- Backend endpoints: `/api/exchange-rate`, `/api/watchlist` (GET/POST/DELETE), `/api/quotes`, `/api/quote/{ticker}`, `/api/history/{ticker}`, `/api/predict/{ticker}`.
- Dashboard with metric tiles (totals/gainers/losers/avg change), grid of stock cards, animated entrance.
- Side sheet with full detail, AI prediction card (gradient + glow), news list with sentiment badges.
- Add Stock dialog with quick suggestions.
- Defaults seeded on first load.

### Iteration 2 (P1 + Smart enhancement)
- **Sparkline 30d** on every card (closes returned inside `/api/quotes`, rendered with recharts).
- **Prediction caching**: `POST /api/predict/{ticker}` reuses any prediction from the last hour; `?force=true` bypasses cache. Cached response served in ~20ms.
- **Compare endpoint** `/api/compare?tickers=A,B[,C,D]` returns 30-day series normalized to base 100. Frontend Compare sheet overlays up to 4 tickers with legend + per-ticker change %.
- **Top Movers shareable PNG**: dialog renders top 3 gainers / top 3 losers with USD + MXN; one-click download via `html-to-image`; Web Share API fallback for mobile.
- 15/15 backend regression tests pass.

### Iteration 3 (P2 — Alerts)
- New collections `alerts`, `ticker_state`.
- **Price-move alerts**: background asyncio task every 10 min + `POST /api/alerts/sync` on dashboard load; emits alert when any watchlist ticker moves ≥ 3% vs last-known price.
- **AI direction-flip alerts**: emitted automatically inside `/api/predict` when the latest prediction's direction differs from the previously stored one.
- Endpoints: `GET /api/alerts`, `POST /api/alerts/sync`, `POST /api/alerts/{id}/read`, `POST /api/alerts/read-all`, `DELETE /api/alerts`.
- Frontend `AlertsBell` with badge counter, popover, mark-as-read, clear-all, click-to-open-detail. Polls every 30s.
- 28/28 backend tests pass (iter 3).

### Iteration 4–5 (Portfolio / Posiciones)
- New collections `position_lots`, `position_targets`.
- **Lot tracking**: each compra es un lote independiente (qty + buy_price_usd + buy_fx_rate + buy_date). Costo promedio ponderado calculado en agregación.
- **Target + Stop-Loss** por ticker (PUT/DELETE `/api/portfolio/target/{ticker}`).
- **Aggregated portfolio** GET `/api/portfolio`: positions[], totals (cost_usd, cost_mxn, value_usd, value_mxn, pnl_usd, pnl_mxn, pnl_pct), mxn_rate.
- **Cross alerts** (`target_hit` / `stop_loss_hit`) cuando el precio cruza el objetivo o stop con cooldown 6h. Solo se emiten si el usuario tiene lotes para ese ticker.
- Frontend: tab toggle Watchlist/Portafolio, summary tiles (invertido / valor / P&L USD+MXN), position cards con P&L, target distance, stop-loss, ganancia proyectada al objetivo, AddLotDialog, SetTargetDialog, LotsListDialog (eliminar lotes).
- 52/52 backend tests pass (iter 5 — fixed critical ordering bug donde `_check_price_moves` sobreescribía `last_price` antes que `_check_target_crosses` lo leyera).

### Iteration 6 (Histórico de operaciones cerradas)
- New collection `closed_trades`.
- **POST `/api/portfolio/sell`** con selector FIFO / LIFO / SPECIFIC + ventas parciales (split de lote). Si un lote queda en 0 se elimina; si queda en parcial sólo se reduce su qty.
- **Métricas por trade**: P&L USD+MXN, % retorno, días sostenidos (promedio ponderado), retorno anualizado, asignación de lotes consumidos.
- **GET `/api/portfolio/trades`** con summary (count, wins, losses, win_rate, total_pnl_usd/mxn, total_return_pct).
- **GET `/api/portfolio/trades/equity-curve`** — agregación mensual con cumulative_usd / cumulative_mxn para gráfica de equity.
- **DELETE `/api/portfolio/trades/{id}`** — borrar del historial.
- Frontend: tercer tab **Historial** con summary tiles, equity curve mensual (recharts AreaChart con punto mensual), tabla de trades con anualizado. Botón "Vender" en cada PositionCard abre `SellPositionDialog` con selector de método y proyección de P&L en vivo.
- 69/69 backend tests pass (iter 6).

### Iteration 7–9 (Auth JWT + Admin role)
- **JWT auth** (bcrypt + Bearer tokens, 7d): `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`. Brute-force protection (5 fails → 15min lockout per IP+email).
- **Admin role**: seeded automáticamente desde `ADMIN_EMAIL` / `ADMIN_PASSWORD` en .env. Password sync si el .env cambia.
- **Data isolation**: TODOS los endpoints existentes ahora requieren auth y filtran por `user_id`. Watchlist, portfolio, lots, targets, trades, alerts, predictions privados por usuario.
- **Vista global admin**: query param `?admin_all=true` desactiva el filtro por user_id (sólo válido si rol=admin; no-admins lo reciben silenciosamente ignorado).
- **Endpoints admin**: `GET /api/admin/users` (listado con stats: watchlist, lots, trades, alerts, unread), `DELETE /api/admin/users/{id}` (cascade delete de todo el contenido del usuario; admin no puede eliminarse a sí mismo).
- **Frontend**: Login/Register pages, `AuthContext` con localStorage, axios interceptor (Bearer + admin_all flag automático), `ProtectedRoute`/`AdminRoute`, `UserMenu` con badge admin + toggle "Vista global" + acceso a `/admin/users`, página AdminUsersPage con tabla de usuarios.
- **Migration**: limpieza one-shot de docs ownerless al startup (purgó 9 watchlist + 205 predictions del estado de desarrollo previo).
- **36/36 tests pass** (iter 9 — corregidos 2 bugs encontrados durante el ciclo: crash KeyError en admin_all y regresión de aislamiento por overwrite de spread `{**scope, user_id: ...}`).

## Backlog (P1)
- Sparkline chart on each card (recharts).
- Push notifications when prediction direction flips.
- Compare mode (overlay two tickers).
- Multi-currency (EUR, BRL).

## P2
- Per-user watchlists via auth.
- Historical predictions accuracy tracking.
- News integration with real provider (NewsAPI / Finnhub).
