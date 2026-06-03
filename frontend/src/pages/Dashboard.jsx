import { useEffect, useMemo, useState, useCallback } from "react";
import { TrendUp, TrendDown, Plus, ArrowsClockwise, ChartLineUp, CurrencyDollar, Scales, Share } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api } from "../lib/api";
import StockCard from "../components/StockCard";
import AddStockDialog from "../components/AddStockDialog";
import StockDetailSheet from "../components/StockDetailSheet";
import CompareSheet from "../components/CompareSheet";
import TopMoversDialog from "../components/TopMoversDialog";
import AlertsBell from "../components/AlertsBell";
import PortfolioPanel from "../components/PortfolioPanel";
import ClosedTradesPanel from "../components/ClosedTradesPanel";
import UserMenu from "../components/UserMenu";
import { Button } from "../components/ui/button";

export default function Dashboard() {
  const [quotes, setQuotes] = useState([]);
  const [mxnRate, setMxnRate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [moversOpen, setMoversOpen] = useState(false);
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [view, setView] = useState("watchlist"); // 'watchlist' | 'portfolio'

  const loadQuotes = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true);
    try {
      const { data } = await api.get("/quotes");
      setQuotes(data.quotes || []);
      setMxnRate(data.mxn_rate);
      setFetchedAt(data.fetched_at);
    } catch (e) {
      toast.error("Could not load quotes", { description: e?.response?.data?.detail || e.message });
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQuotes();
    // Fire-and-forget: trigger backend price-move alert check on load
    api.post("/alerts/sync").catch(() => {});
    const id = setInterval(() => loadQuotes(true), 60000);
    return () => clearInterval(id);
  }, [loadQuotes]);

  const stats = useMemo(() => {
    const gainers = quotes.filter((q) => (q.change_percent ?? 0) > 0).length;
    const losers = quotes.filter((q) => (q.change_percent ?? 0) < 0).length;
    const avg =
      quotes.length > 0
        ? quotes.reduce((s, q) => s + (q.change_percent ?? 0), 0) / quotes.length
        : 0;
    return { gainers, losers, avg };
  }, [quotes]);

  const handleAdd = async (ticker) => {
    try {
      await api.post("/watchlist", { ticker });
      toast.success(`${ticker.toUpperCase()} added to watchlist`);
      setAddOpen(false);
      await loadQuotes();
    } catch (e) {
      toast.error("Could not add ticker", { description: e?.response?.data?.detail || e.message });
    }
  };

  const handleRemove = async (ticker) => {
    try {
      await api.delete(`/watchlist/${ticker}`);
      toast.success(`${ticker} removed`);
      setQuotes((q) => q.filter((x) => x.ticker !== ticker));
    } catch (e) {
      toast.error("Could not remove", { description: e?.response?.data?.detail || e.message });
    }
  };

  return (
    <div className="min-h-screen grain" data-testid="dashboard-root">
      {/* Top bar */}
      <header className="border-b border-line sticky top-0 z-30 backdrop-blur-xl bg-obsidian/80">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 grid place-items-center rounded-lg bg-brand/10 border border-brand/30">
              <ChartLineUp size={20} weight="duotone" className="text-brand" />
            </div>
            <div>
              <h1 className="text-heading text-base sm:text-lg font-semibold tracking-tight">
                Tablero <span className="text-ink-secondary font-normal">/ NASDAQ · NYSE</span>
              </h1>
              <p className="text-xs text-ink-muted text-mono">
                {fetchedAt ? new Date(fetchedAt).toLocaleTimeString("es-MX") : "—"} · live
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <div className="hidden md:flex items-center gap-2 px-3 py-2 rounded-lg border border-line bg-obsidian-surface" data-testid="mxn-rate-display">
              <CurrencyDollar size={16} weight="bold" className="text-brand" />
              <span className="text-xs text-ink-secondary">USD/MXN</span>
              <span className="text-mono text-sm text-ink-primary font-semibold">
                {mxnRate ? mxnRate.toFixed(4) : "—"}
              </span>
            </div>
            <AlertsBell onAlertClick={(t) => setSelectedTicker(t)} />
            <UserMenu />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMoversOpen(true)}
              disabled={quotes.length === 0}
              data-testid="top-movers-btn"
              className="border-line bg-obsidian-surface hover:bg-obsidian-hover hover:text-ink-primary text-ink-secondary"
            >
              <Share size={16} weight="bold" />
              <span className="hidden sm:inline ml-2">Top Movers</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCompareOpen(true)}
              disabled={quotes.length < 2}
              data-testid="compare-btn"
              className="border-line bg-obsidian-surface hover:bg-obsidian-hover hover:text-ink-primary text-ink-secondary"
            >
              <Scales size={16} weight="bold" />
              <span className="hidden sm:inline ml-2">Comparar</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => loadQuotes()}
              disabled={refreshing}
              data-testid="refresh-btn"
              className="border-line bg-obsidian-surface hover:bg-obsidian-hover hover:text-ink-primary text-ink-secondary"
            >
              <ArrowsClockwise size={16} className={refreshing ? "animate-spin" : ""} />
              <span className="hidden sm:inline ml-2">Refrescar</span>
            </Button>
            <Button
              size="sm"
              onClick={() => setAddOpen(true)}
              data-testid="add-stock-btn"
              className="bg-brand hover:bg-brand-hover text-white"
            >
              <Plus size={16} weight="bold" />
              <span className="ml-2">Añadir</span>
            </Button>
          </div>
        </div>
      </header>

      {/* View toggle */}
      <section className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        <div className="inline-flex items-center rounded-lg border border-line bg-obsidian-surface p-1" data-testid="view-toggle">
          <button
            type="button"
            onClick={() => setView("watchlist")}
            data-testid="view-watchlist"
            className={`text-xs uppercase tracking-widest px-4 py-2 rounded-md transition-colors ${
              view === "watchlist" ? "bg-brand/15 text-brand" : "text-ink-secondary hover:text-ink-primary"
            }`}
          >
            Watchlist
          </button>
          <button
            type="button"
            onClick={() => setView("portfolio")}
            data-testid="view-portfolio"
            className={`text-xs uppercase tracking-widest px-4 py-2 rounded-md transition-colors ${
              view === "portfolio" ? "bg-brand/15 text-brand" : "text-ink-secondary hover:text-ink-primary"
            }`}
          >
            Portafolio
          </button>
          <button
            type="button"
            onClick={() => setView("history")}
            data-testid="view-history"
            className={`text-xs uppercase tracking-widest px-4 py-2 rounded-md transition-colors ${
              view === "history" ? "bg-brand/15 text-brand" : "text-ink-secondary hover:text-ink-primary"
            }`}
          >
            Historial
          </button>
        </div>
      </section>

      {view === "watchlist" ? (
        <>
          {/* Metric strip */}
          <section className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 pt-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6">
              <MetricTile label="Activos" value={quotes.length} testId="metric-total" />
              <MetricTile
                label="Al alza"
                value={stats.gainers}
                tone="bull"
                icon={<TrendUp size={16} weight="bold" />}
                testId="metric-gainers"
              />
              <MetricTile
                label="A la baja"
                value={stats.losers}
                tone="bear"
                icon={<TrendDown size={16} weight="bold" />}
                testId="metric-losers"
              />
              <MetricTile
                label="Cambio prom."
                value={`${stats.avg >= 0 ? "+" : ""}${stats.avg.toFixed(2)}%`}
                tone={stats.avg >= 0 ? "bull" : "bear"}
                testId="metric-avg"
              />
            </div>
          </section>

          {/* Grid */}
          <main className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-heading text-sm font-medium text-ink-secondary uppercase tracking-widest">
                Watchlist
              </h2>
              <span className="text-mono text-xs text-ink-muted">
                {quotes.length} símbolos
              </span>
            </div>

            {loading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 md:gap-6">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-44 rounded-xl border border-line bg-obsidian-surface animate-pulse" />
                ))}
              </div>
            ) : quotes.length === 0 ? (
              <EmptyState onAdd={() => setAddOpen(true)} />
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 md:gap-6" data-testid="stock-grid">
                {quotes.map((q, idx) => (
                  <div
                    key={q.ticker}
                    className="animate-fade-up"
                    style={{ animationDelay: `${idx * 35}ms` }}
                  >
                    <StockCard
                      quote={q}
                      onSelect={() => setSelectedTicker(q.ticker)}
                      onRemove={() => handleRemove(q.ticker)}
                    />
                  </div>
                ))}
              </div>
            )}
          </main>
        </>
      ) : view === "portfolio" ? (
        <main className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <PortfolioPanel mxnRate={mxnRate} watchlistTickers={quotes.map((q) => q.ticker)} />
        </main>
      ) : (
        <main className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <ClosedTradesPanel />
        </main>
      )}

      <AddStockDialog open={addOpen} onOpenChange={setAddOpen} onAdd={handleAdd} />
      <CompareSheet
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        tickers={quotes.map((q) => q.ticker)}
        available={quotes.map((q) => q.ticker)}
      />
      <TopMoversDialog
        open={moversOpen}
        onOpenChange={setMoversOpen}
        quotes={quotes}
        mxnRate={mxnRate}
      />
      <StockDetailSheet
        ticker={selectedTicker}
        open={!!selectedTicker}
        onClose={() => setSelectedTicker(null)}
        mxnRate={mxnRate}
      />
    </div>
  );
}

function MetricTile({ label, value, tone, icon, testId }) {
  const toneCls =
    tone === "bull"
      ? "text-bull"
      : tone === "bear"
      ? "text-bear"
      : "text-ink-primary";
  return (
    <div
      className="rounded-xl border border-line bg-obsidian-surface p-5 transition-all duration-200 hover:bg-obsidian-hover hover:border-line-focus"
      data-testid={testId}
    >
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-widest text-ink-muted">{label}</p>
        {icon && <span className={toneCls}>{icon}</span>}
      </div>
      <p className={`text-mono text-2xl md:text-3xl font-semibold mt-3 ${toneCls}`}>{value}</p>
    </div>
  );
}

function EmptyState({ onAdd }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-obsidian-surface/40 p-16 text-center">
      <ChartLineUp size={48} weight="duotone" className="text-ink-muted mx-auto mb-4" />
      <h3 className="text-heading text-xl font-semibold mb-2">Tu watchlist está vacía</h3>
      <p className="text-ink-secondary text-sm mb-6">Agrega tu primer ticker para comenzar</p>
      <Button onClick={onAdd} className="bg-brand hover:bg-brand-hover text-white">
        <Plus size={16} weight="bold" className="mr-2" /> Añadir acción
      </Button>
    </div>
  );
}
