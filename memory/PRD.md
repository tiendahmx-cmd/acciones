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

## Backlog (P1)
- Sparkline chart on each card (recharts).
- Push notifications when prediction direction flips.
- Compare mode (overlay two tickers).
- Multi-currency (EUR, BRL).

## P2
- Per-user watchlists via auth.
- Historical predictions accuracy tracking.
- News integration with real provider (NewsAPI / Finnhub).
