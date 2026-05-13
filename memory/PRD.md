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

## Backlog (P1)
- Sparkline chart on each card (recharts).
- Push notifications when prediction direction flips.
- Compare mode (overlay two tickers).
- Multi-currency (EUR, BRL).

## P2
- Per-user watchlists via auth.
- Historical predictions accuracy tracking.
- News integration with real provider (NewsAPI / Finnhub).
