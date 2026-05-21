import { TrendUp, TrendDown, X } from "@phosphor-icons/react";
import { fmtUSD, fmtMXN, fmtPct, fmtNumber } from "../lib/api";
import Sparkline from "./Sparkline";

export default function StockCard({ quote, onSelect, onRemove }) {
  const isUp = (quote.change_percent ?? 0) >= 0;
  const toneText = isUp ? "text-bull" : "text-bear";
  const toneBg = isUp ? "bg-bull-soft" : "bg-bear-soft";
  const toneBorder = isUp ? "border-bull-line" : "border-bear-line";

  return (
    <div
      className="group relative rounded-xl border border-line bg-obsidian-surface p-5 md:p-6 transition-all duration-200 hover:bg-obsidian-hover hover:border-line-focus hover:-translate-y-1 cursor-pointer"
      onClick={onSelect}
      data-testid={`stock-card-${quote.ticker}`}
    >
      {/* Remove */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="absolute top-3 right-3 w-7 h-7 grid place-items-center rounded-md text-ink-muted opacity-0 group-hover:opacity-100 hover:text-bear hover:bg-bear-soft transition-all"
        data-testid={`remove-${quote.ticker}`}
        aria-label={`Remove ${quote.ticker}`}
      >
        <X size={14} weight="bold" />
      </button>

      {/* Header: ticker + name */}
      <div className="flex items-start justify-between pr-8">
        <div className="min-w-0">
          <p className="text-mono text-base font-bold tracking-wider text-ink-primary">
            {quote.ticker}
          </p>
          <p className="text-xs text-ink-secondary truncate mt-1" title={quote.name}>
            {quote.name || quote.exchange || "—"}
          </p>
        </div>
        <div
          className={`flex items-center gap-1 px-2 py-1 rounded-md border text-mono text-xs font-semibold ${toneText} ${toneBg} ${toneBorder}`}
          data-testid={`change-${quote.ticker}`}
        >
          {isUp ? <TrendUp size={12} weight="bold" /> : <TrendDown size={12} weight="bold" />}
          {fmtPct(quote.change_percent)}
        </div>
      </div>

      {/* Prices */}
      <div className="mt-5">
        <p className="text-mono text-3xl font-semibold tracking-tight text-ink-primary" data-testid={`price-usd-${quote.ticker}`}>
          {fmtUSD(quote.price)}
        </p>
        <p className="text-mono text-xl font-medium text-ink-secondary mt-1" data-testid={`price-mxn-${quote.ticker}`}>
          {fmtMXN(quote.price_mxn)} <span className="text-ink-muted text-xs">MXN</span>
        </p>
      </div>

      {/* Sparkline 30d */}
      <div className="mt-3 -mx-1" data-testid={`sparkline-${quote.ticker}`}>
        <Sparkline data={quote.sparkline || []} isUp={isUp} height={40} />
      </div>

      {/* OHL row */}
      <div className="mt-3 pt-4 border-t border-line grid grid-cols-3 gap-2">
        <Stat label="Apertura" value={fmtNumber(quote.open)} />
        <Stat label="Máximo" value={fmtNumber(quote.high)} />
        <Stat label="Mínimo" value={fmtNumber(quote.low)} />
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className="text-mono text-sm text-ink-primary mt-1">{value}</p>
    </div>
  );
}
