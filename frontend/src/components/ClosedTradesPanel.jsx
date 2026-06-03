import { useEffect, useState } from "react";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Area, AreaChart } from "recharts";
import { ClockCounterClockwise, TrendUp, TrendDown, Trash, ChartLineUp, DownloadSimple } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, fmtUSD, fmtMXN, fmtPct, fmtNumber, API } from "../lib/api";

export default function ClosedTradesPanel() {
  const [data, setData] = useState(null);
  const [equity, setEquity] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [{ data: trades }, { data: curve }] = await Promise.all([
        api.get("/portfolio/trades"),
        api.get("/portfolio/trades/equity-curve"),
      ]);
      setData(trades);
      setEquity(curve.points || []);
    } catch (e) {
      toast.error("No se pudo cargar el historial");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const removeTrade = async (id) => {
    try {
      await api.delete(`/portfolio/trades/${id}`);
      toast.success("Operación eliminada del historial");
      await load();
    } catch (e) {
      toast.error("No se pudo eliminar");
    }
  };

  const exportCsv = async () => {
    try {
      const adminAll = localStorage.getItem("admin_all") === "1";
      const url = `${API}/portfolio/trades/export.csv${adminAll ? "?admin_all=true" : ""}`;
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${localStorage.getItem("auth_token") || ""}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const link = document.createElement("a");
      link.href = window.URL.createObjectURL(blob);
      link.download = `operaciones-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      window.URL.revokeObjectURL(link.href);
      toast.success("CSV descargado");
    } catch (e) {
      toast.error("No se pudo exportar", { description: e.message });
    }
  };

  const summary = data?.summary;
  const trades = data?.trades || [];
  const totalProfit = (summary?.total_pnl_usd ?? 0) >= 0;

  return (
    <div data-testid="trades-panel">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-8">
        <SummaryTile label="Operaciones" primary={fmtNumber(summary?.count || 0)} secondary={`${summary?.wins || 0}W · ${summary?.losses || 0}L`} testId="metric-count" />
        <SummaryTile label="Win-rate" primary={`${summary?.win_rate?.toFixed(1) ?? "0.0"}%`} secondary={summary?.count ? `de ${summary.count} trades` : "Sin datos"} tone={(summary?.win_rate ?? 0) >= 50 ? "bull" : "bear"} testId="metric-winrate" />
        <SummaryTile label="P&L total USD" primary={fmtUSD(summary?.total_pnl_usd)} secondary={fmtPct(summary?.total_return_pct)} tone={totalProfit ? "bull" : "bear"} testId="metric-pnl-usd" />
        <SummaryTile label="P&L total MXN" primary={fmtMXN(summary?.total_pnl_mxn)} secondary="Realizado" tone={(summary?.total_pnl_mxn ?? 0) >= 0 ? "bull" : "bear"} testId="metric-pnl-mxn" />
      </div>

      {/* Equity curve */}
      <div className="rounded-xl border border-line bg-obsidian-surface p-5 md:p-6 mb-8" data-testid="equity-curve">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-heading text-sm font-medium text-ink-secondary uppercase tracking-widest flex items-center gap-2">
            <ChartLineUp size={14} weight="duotone" className="text-brand" /> Curva de equity (mensual acumulado)
          </h3>
          <span className="text-mono text-xs text-ink-muted">USD</span>
        </div>
        {equity.length === 0 ? (
          <p className="text-sm text-ink-muted py-8 text-center">Sin operaciones cerradas todavía. Vende una posición para ver tu curva.</p>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equity}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1E232B" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" stroke="#475569" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
                <YAxis stroke="#475569" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} tickFormatter={(v) => `$${v.toFixed(0)}`} />
                <Tooltip
                  contentStyle={{ background: "#0E1116", border: "1px solid #1E232B", borderRadius: 8, fontFamily: "JetBrains Mono", fontSize: 12 }}
                  labelStyle={{ color: "#94A3B8" }}
                  formatter={(value, name) => [fmtUSD(value), name === "cumulative_usd" ? "Acumulado" : "Mensual"]}
                />
                <Area type="monotone" dataKey="cumulative_usd" stroke="#3B82F6" strokeWidth={2} fill="url(#eqGrad)" />
                <Line type="monotone" dataKey="pnl_usd" stroke="#10B981" strokeWidth={1} dot={{ r: 3 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Trades list */}
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <h2 className="text-heading text-sm font-medium text-ink-secondary uppercase tracking-widest">Operaciones cerradas</h2>
        <div className="flex items-center gap-3">
          <span className="text-mono text-xs text-ink-muted">{trades.length}</span>
          <button
            type="button"
            onClick={exportCsv}
            disabled={trades.length === 0}
            data-testid="export-csv"
            className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-md border border-line bg-obsidian-surface text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary hover:border-line-focus transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <DownloadSimple size={14} weight="bold" /> Exportar CSV
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-16 rounded-lg border border-line bg-obsidian-surface animate-pulse" />)}
        </div>
      ) : trades.length === 0 ? (
        <EmptyTrades />
      ) : (
        <ul className="space-y-2" data-testid="trades-list">
          {trades.map((t) => <TradeRow key={t.id} trade={t} onRemove={() => removeTrade(t.id)} />)}
        </ul>
      )}
    </div>
  );
}

function SummaryTile({ label, primary, secondary, tone, testId }) {
  const cls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-primary";
  return (
    <div className="rounded-xl border border-line bg-obsidian-surface p-5 transition-all duration-200 hover:bg-obsidian-hover hover:border-line-focus" data-testid={testId}>
      <p className="text-xs uppercase tracking-widest text-ink-muted">{label}</p>
      <p className={`text-mono text-2xl font-semibold mt-3 ${cls}`}>{primary}</p>
      <p className="text-mono text-base text-ink-secondary mt-1">{secondary}</p>
    </div>
  );
}

function TradeRow({ trade, onRemove }) {
  const profit = (trade.pnl_usd ?? 0) >= 0;
  const tone = profit ? "text-bull" : "text-bear";
  const Icon = profit ? TrendUp : TrendDown;
  return (
    <li className="rounded-xl border border-line bg-obsidian-surface px-4 py-4 hover:bg-obsidian-hover transition-colors" data-testid={`trade-${trade.id}`}>
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-[120px]">
          <div className={`w-8 h-8 grid place-items-center rounded-md ${profit ? "bg-bull-soft" : "bg-bear-soft"} ${tone}`}>
            <Icon size={14} weight="bold" />
          </div>
          <div>
            <p className="text-mono text-sm font-bold tracking-wider">{trade.ticker}</p>
            <p className="text-[10px] uppercase tracking-widest text-ink-muted">{trade.method}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 flex-1 text-mono text-xs">
          <Cell label="Vendido" value={`${fmtNumber(trade.qty_sold)} @ ${fmtUSD(trade.sell_price_usd)}`} />
          <Cell label="Fecha" value={trade.sell_date} />
          <Cell label="Días" value={fmtNumber(trade.avg_days_held)} />
          <Cell label="P&L" value={`${profit ? "+" : ""}${fmtUSD(trade.pnl_usd)}`} tone={tone} />
          <Cell label="Retorno" value={fmtPct(trade.return_pct)} tone={tone} />
        </div>
        <div className="text-right ml-auto">
          <p className={`text-mono text-lg font-semibold ${tone}`}>{(trade.pnl_mxn ?? 0) >= 0 ? "+" : ""}{fmtMXN(trade.pnl_mxn)} <span className="text-ink-muted text-[10px]">MXN</span></p>
          {trade.annualized_return_pct != null && (
            <p className="text-[10px] uppercase tracking-widest text-ink-muted mt-0.5">Anualizado {fmtPct(trade.annualized_return_pct)}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="w-7 h-7 grid place-items-center rounded-md text-ink-muted hover:bg-bear-soft hover:text-bear transition-colors"
          title="Eliminar del historial"
          data-testid={`delete-trade-${trade.id}`}
        >
          <Trash size={12} />
        </button>
      </div>
    </li>
  );
}

function Cell({ label, value, tone }) {
  const cls = tone || "text-ink-primary";
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className={`mt-0.5 ${cls}`}>{value}</p>
    </div>
  );
}

function EmptyTrades() {
  return (
    <div className="rounded-xl border border-dashed border-line bg-obsidian-surface/40 p-16 text-center">
      <ClockCounterClockwise size={48} weight="duotone" className="text-ink-muted mx-auto mb-4" />
      <h3 className="text-heading text-xl font-semibold mb-2">Sin operaciones cerradas</h3>
      <p className="text-ink-secondary text-sm">Cuando vendas una posición aparecerá aquí con tu P&L realizado.</p>
    </div>
  );
}
