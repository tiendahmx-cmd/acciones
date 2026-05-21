import { useEffect, useMemo, useState } from "react";
import { Plus, Pencil, Wallet, X, Target, Shield, TrendUp, TrendDown, Trash, Calendar, ChartLineUp, CashRegister } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, fmtUSD, fmtMXN, fmtPct, fmtNumber } from "../lib/api";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import SellPositionDialog from "./SellPositionDialog";

export default function PortfolioPanel({ mxnRate, watchlistTickers = [] }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState(null);   // ticker
  const [viewLots, setViewLots] = useState(null);       // ticker
  const [sellTicker, setSellTicker] = useState(null);   // ticker

  const load = async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get("/portfolio");
      setData(res);
    } catch (e) {
      toast.error("No se pudo cargar el portafolio");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const totals = data?.totals;
  const positions = data?.positions || [];

  return (
    <div data-testid="portfolio-panel">
      {/* Totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-8">
        <SummaryTile
          label="Invertido"
          primary={fmtUSD(totals?.cost_usd)}
          secondary={fmtMXN(totals?.cost_mxn) + " MXN"}
          testId="total-invested"
        />
        <SummaryTile
          label="Valor actual"
          primary={fmtUSD(totals?.value_usd)}
          secondary={fmtMXN(totals?.value_mxn) + " MXN"}
          testId="total-value"
        />
        <SummaryTile
          label="P&L USD"
          primary={fmtUSD(totals?.pnl_usd)}
          secondary={fmtPct(totals?.pnl_pct)}
          tone={totals?.pnl_usd >= 0 ? "bull" : "bear"}
          testId="total-pnl-usd"
        />
        <SummaryTile
          label="P&L MXN"
          primary={fmtMXN(totals?.pnl_mxn)}
          secondary={`USD/MXN ${data?.mxn_rate?.toFixed(4) ?? "—"}`}
          tone={totals?.pnl_mxn >= 0 ? "bull" : "bear"}
          testId="total-pnl-mxn"
        />
      </div>

      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-heading text-sm font-medium text-ink-secondary uppercase tracking-widest">
          Posiciones
        </h2>
        <Button
          size="sm"
          onClick={() => setAddOpen(true)}
          data-testid="add-lot-btn"
          className="bg-brand hover:bg-brand-hover text-white"
        >
          <Plus size={16} weight="bold" className="mr-2" /> Registrar compra
        </Button>
      </div>

      {/* Positions */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-56 rounded-xl border border-line bg-obsidian-surface animate-pulse" />
          ))}
        </div>
      ) : positions.length === 0 ? (
        <EmptyState onAdd={() => setAddOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
          {positions.map((p) => (
            <PositionCard
              key={p.ticker}
              pos={p}
              onSetTarget={() => setEditTarget(p.ticker)}
              onViewLots={() => setViewLots(p.ticker)}
              onSell={() => setSellTicker(p.ticker)}
            />
          ))}
        </div>
      )}

      <AddLotDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        defaultRate={mxnRate}
        watchlistTickers={watchlistTickers}
        onAdded={async () => {
          setAddOpen(false);
          await load();
        }}
      />
      <SetTargetDialog
        ticker={editTarget}
        position={positions.find((p) => p.ticker === editTarget)}
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        onSaved={async () => {
          setEditTarget(null);
          await load();
        }}
      />
      <LotsListDialog
        ticker={viewLots}
        open={!!viewLots}
        onClose={() => setViewLots(null)}
        onChanged={async () => {
          await load();
        }}
      />
      <SellPositionDialog
        position={positions.find((p) => p.ticker === sellTicker)}
        open={!!sellTicker}
        onClose={() => setSellTicker(null)}
        onSold={async () => {
          setSellTicker(null);
          await load();
        }}
        defaultRate={mxnRate}
      />
    </div>
  );
}

function SummaryTile({ label, primary, secondary, tone, testId }) {
  const toneCls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-primary";
  return (
    <div className="rounded-xl border border-line bg-obsidian-surface p-5 transition-all duration-200 hover:bg-obsidian-hover hover:border-line-focus" data-testid={testId}>
      <p className="text-xs uppercase tracking-widest text-ink-muted">{label}</p>
      <p className={`text-mono text-2xl font-semibold mt-3 ${toneCls}`}>{primary}</p>
      <p className="text-mono text-base text-ink-secondary mt-1">{secondary}</p>
    </div>
  );
}

function PositionCard({ pos, onSetTarget, onViewLots, onSell }) {
  const isProfit = (pos.pnl_pct ?? 0) >= 0;
  const toneCls = isProfit ? "text-bull" : "text-bear";
  const Icon = isProfit ? TrendUp : TrendDown;
  return (
    <div
      className="rounded-xl border border-line bg-obsidian-surface p-5 md:p-6 transition-all duration-200 hover:bg-obsidian-hover hover:border-line-focus"
      data-testid={`position-${pos.ticker}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-mono text-base font-bold tracking-wider text-ink-primary">{pos.ticker}</p>
          <p className="text-xs text-ink-secondary mt-1 text-mono">
            {fmtNumber(pos.qty)} sh · costo {fmtUSD(pos.avg_cost_usd)}
          </p>
        </div>
        <div className={`flex items-center gap-1 px-2 py-1 rounded-md border text-mono text-xs font-semibold ${toneCls} ${isProfit ? "bg-bull-soft border-bull-line" : "bg-bear-soft border-bear-line"}`}>
          <Icon size={12} weight="bold" />
          {fmtPct(pos.pnl_pct)}
        </div>
      </div>

      <div className="mt-5">
        <p className={`text-mono text-3xl font-semibold tracking-tight ${toneCls}`}>
          {(pos.pnl_usd ?? 0) >= 0 ? "+" : ""}{fmtUSD(pos.pnl_usd)}
        </p>
        <p className={`text-mono text-xl font-medium mt-1 ${toneCls}`}>
          {(pos.pnl_mxn ?? 0) >= 0 ? "+" : ""}{fmtMXN(pos.pnl_mxn)} <span className="text-ink-muted text-xs">MXN</span>
        </p>
      </div>

      <div className="mt-5 pt-4 border-t border-line grid grid-cols-2 gap-3 text-xs">
        <Row label="Precio actual" value={fmtUSD(pos.current_price)} />
        <Row label="Valor mercado" value={fmtUSD(pos.market_value_usd)} />
      </div>

      {/* Target */}
      <div className="mt-4 rounded-lg border border-line p-3 bg-obsidian">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs text-ink-secondary">
            <Target size={12} weight="bold" className="text-brand" />
            Objetivo
          </div>
          <button
            type="button"
            onClick={onSetTarget}
            className="text-xs text-ink-secondary hover:text-ink-primary flex items-center gap-1"
            data-testid={`set-target-${pos.ticker}`}
          >
            <Pencil size={11} /> {pos.target_price ? "Editar" : "Definir"}
          </button>
        </div>
        {pos.target_price ? (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-mono text-sm">
              <span className="text-ink-primary">{fmtUSD(pos.target_price)}</span>
              <span className={`text-xs ${(pos.target_distance_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>
                {(pos.target_distance_pct ?? 0) >= 0 ? "+" : ""}{pos.target_distance_pct?.toFixed(2)}%
              </span>
            </div>
            <p className="text-[10px] uppercase tracking-widest text-ink-muted">
              Ganancia al objetivo: <span className="text-bull">{fmtUSD(pos.target_pnl_usd)} ({fmtPct(pos.target_pnl_pct)})</span>
            </p>
            {pos.stop_loss_price && (
              <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-ink-muted pt-1">
                <span className="flex items-center gap-1">
                  <Shield size={10} weight="bold" className="text-bear" /> Stop {fmtUSD(pos.stop_loss_price)}
                </span>
                <span className="text-bear">{pos.stop_distance_pct?.toFixed(2)}% sobre</span>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Sin precio objetivo definido</p>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={onViewLots}
          className="text-xs text-ink-secondary hover:text-ink-primary flex items-center gap-1"
          data-testid={`view-lots-${pos.ticker}`}
        >
          <Calendar size={12} /> Ver lotes ({pos.lots_count})
        </button>
        <button
          type="button"
          onClick={onSell}
          className="text-xs flex items-center gap-1 px-2.5 py-1 rounded-md border border-line bg-obsidian text-ink-secondary hover:bg-bull-soft hover:text-bull hover:border-bull-line transition-colors"
          data-testid={`sell-${pos.ticker}`}
        >
          <CashRegister size={12} weight="bold" /> Vender
        </button>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className="text-mono text-sm text-ink-primary mt-1">{value}</p>
    </div>
  );
}

function EmptyState({ onAdd }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-obsidian-surface/40 p-16 text-center">
      <Wallet size={48} weight="duotone" className="text-ink-muted mx-auto mb-4" />
      <h3 className="text-heading text-xl font-semibold mb-2">Sin posiciones</h3>
      <p className="text-ink-secondary text-sm mb-6">Registra tu primera compra para comenzar a trackear ganancias</p>
      <Button onClick={onAdd} className="bg-brand hover:bg-brand-hover text-white" data-testid="empty-add-lot">
        <Plus size={16} weight="bold" className="mr-2" /> Registrar compra
      </Button>
    </div>
  );
}

function AddLotDialog({ open, onOpenChange, defaultRate, watchlistTickers, onAdded }) {
  const [ticker, setTicker] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [fx, setFx] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setTicker("");
      setQty("");
      setPrice("");
      setFx(defaultRate ? defaultRate.toFixed(4) : "");
      setDate(new Date().toISOString().slice(0, 10));
    }
  }, [open, defaultRate]);

  const submit = async (e) => {
    e?.preventDefault();
    if (!ticker || !qty || !price) return;
    setBusy(true);
    try {
      await api.post("/portfolio/lots", {
        ticker: ticker.toUpperCase(),
        qty: parseFloat(qty),
        buy_price_usd: parseFloat(price),
        buy_fx_rate: fx ? parseFloat(fx) : undefined,
        buy_date: date,
      });
      toast.success(`Compra de ${ticker.toUpperCase()} registrada`);
      onAdded?.();
    } catch (err) {
      toast.error("No se pudo guardar", { description: err?.response?.data?.detail || err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-obsidian-surface border-line text-ink-primary sm:max-w-md" data-testid="add-lot-dialog">
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight">Registrar compra</DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Cada lote conserva su precio y tipo de cambio originales. El sistema calcula el costo promedio ponderado.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Ticker</Label>
            <Input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="NVDA"
              className="bg-obsidian border-line text-mono uppercase tracking-widest mt-1.5 focus-visible:ring-brand"
              data-testid="lot-ticker"
              maxLength={10}
              list="lot-ticker-list"
              required
            />
            <datalist id="lot-ticker-list">
              {watchlistTickers.map((t) => <option key={t} value={t} />)}
            </datalist>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">Cantidad</Label>
              <Input
                type="number"
                step="0.0001"
                min="0"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                placeholder="10"
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="lot-qty"
                required
              />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">Precio USD</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="180.50"
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="lot-price"
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">USD/MXN</Label>
              <Input
                type="number"
                step="0.0001"
                min="0"
                value={fx}
                onChange={(e) => setFx(e.target.value)}
                placeholder="17.20"
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="lot-fx"
              />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">Fecha</Label>
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="lot-date"
              />
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary">
              Cancelar
            </Button>
            <Button type="submit" disabled={busy} className="bg-brand hover:bg-brand-hover text-white" data-testid="confirm-add-lot">
              {busy ? "Guardando..." : "Guardar compra"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SetTargetDialog({ ticker, position, open, onClose, onSaved }) {
  const [target, setTarget] = useState("");
  const [stop, setStop] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && position) {
      setTarget(position.target_price ? String(position.target_price) : "");
      setStop(position.stop_loss_price ? String(position.stop_loss_price) : "");
    }
  }, [open, position]);

  const submit = async (e) => {
    e?.preventDefault();
    setBusy(true);
    try {
      await api.put(`/portfolio/target/${ticker}`, {
        target_price: target ? parseFloat(target) : null,
        stop_loss_price: stop ? parseFloat(stop) : null,
      });
      toast.success("Objetivo actualizado");
      onSaved?.();
    } catch (err) {
      toast.error("No se pudo guardar", { description: err?.response?.data?.detail || err.message });
    } finally {
      setBusy(false);
    }
  };

  const removeTarget = async () => {
    setBusy(true);
    try {
      await api.delete(`/portfolio/target/${ticker}`);
      toast.success("Objetivo eliminado");
      onSaved?.();
    } catch (err) {
      toast.error("No se pudo eliminar");
    } finally {
      setBusy(false);
    }
  };

  const projected = useMemo(() => {
    if (!position || !target) return null;
    const t = parseFloat(target);
    if (!t || !position.qty || !position.avg_cost_usd) return null;
    const pnl = (t - position.avg_cost_usd) * position.qty;
    const pct = ((t - position.avg_cost_usd) / position.avg_cost_usd) * 100;
    return { pnl, pct };
  }, [position, target]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-obsidian-surface border-line text-ink-primary sm:max-w-md" data-testid="set-target-dialog">
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight flex items-center gap-2">
            <Target size={18} weight="duotone" className="text-brand" /> Precio objetivo · {ticker}
          </DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Cuando el precio cruza el objetivo o stop-loss aparecerá una alerta en la campana.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Precio objetivo (USD)</Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="250.00"
              className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
              data-testid="target-input"
            />
            {position?.current_price && target && (
              <p className="text-[10px] uppercase tracking-widest text-ink-muted mt-1.5">
                Distancia desde {fmtUSD(position.current_price)}: {(((parseFloat(target) - position.current_price) / position.current_price) * 100).toFixed(2)}%
              </p>
            )}
            {projected && (
              <p className="text-[10px] uppercase tracking-widest text-ink-muted mt-1">
                Ganancia proyectada: <span className="text-bull">{fmtUSD(projected.pnl)} ({projected.pct >= 0 ? "+" : ""}{projected.pct.toFixed(2)}%)</span>
              </p>
            )}
          </div>
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted flex items-center gap-1">
              <Shield size={10} weight="bold" className="text-bear" /> Stop-Loss USD (opcional)
            </Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              value={stop}
              onChange={(e) => setStop(e.target.value)}
              placeholder="190.00"
              className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
              data-testid="stop-input"
            />
          </div>

          <DialogFooter className="gap-2">
            {position?.target_price && (
              <Button type="button" variant="outline" onClick={removeTarget} disabled={busy} className="border-bear-line bg-bear-soft text-bear hover:bg-bear hover:text-white" data-testid="remove-target">
                Eliminar
              </Button>
            )}
            <Button type="button" variant="outline" onClick={onClose} className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary">
              Cancelar
            </Button>
            <Button type="submit" disabled={busy || (!target && !stop)} className="bg-brand hover:bg-brand-hover text-white" data-testid="save-target">
              {busy ? "Guardando..." : "Guardar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LotsListDialog({ ticker, open, onClose, onChanged }) {
  const [lots, setLots] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!ticker) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/portfolio/lots/${ticker}`);
      setLots(data.lots || []);
    } catch (e) {
      toast.error("Error al cargar lotes");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, open]);

  const removeLot = async (id) => {
    try {
      await api.delete(`/portfolio/lots/${id}`);
      toast.success("Lote eliminado");
      await load();
      onChanged?.();
    } catch (e) {
      toast.error("No se pudo eliminar");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-obsidian-surface border-line text-ink-primary sm:max-w-lg" data-testid="lots-dialog">
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight flex items-center gap-2">
            <ChartLineUp size={18} weight="duotone" className="text-brand" /> Lotes · {ticker}
          </DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Cada compra se mantiene independiente. El costo promedio ponderado se calcula automáticamente.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="space-y-2">
            <div className="h-12 bg-obsidian-hover rounded animate-pulse" />
            <div className="h-12 bg-obsidian-hover rounded animate-pulse" />
          </div>
        ) : lots.length === 0 ? (
          <p className="text-sm text-ink-muted text-center py-6">Sin lotes</p>
        ) : (
          <ul className="space-y-2 max-h-[400px] overflow-y-auto scrollbar-thin">
            {lots.map((lot) => (
              <li key={lot.id} data-testid={`lot-${lot.id}`} className="flex items-center justify-between rounded-lg border border-line bg-obsidian px-4 py-3">
                <div className="grid grid-cols-3 gap-4 flex-1 text-mono text-xs">
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-ink-muted">Fecha</p>
                    <p className="text-ink-primary mt-0.5">{lot.buy_date}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-ink-muted">Cantidad</p>
                    <p className="text-ink-primary mt-0.5">{fmtNumber(lot.qty)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-ink-muted">Precio</p>
                    <p className="text-ink-primary mt-0.5">{fmtUSD(lot.buy_price_usd)}</p>
                    <p className="text-[10px] text-ink-muted">@ {lot.buy_fx_rate?.toFixed(4)} MXN</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeLot(lot.id)}
                  className="ml-3 w-7 h-7 grid place-items-center rounded-md text-ink-muted hover:bg-bear-soft hover:text-bear transition-colors"
                  title="Eliminar lote"
                  data-testid={`delete-lot-${lot.id}`}
                >
                  <Trash size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <DialogFooter>
          <Button onClick={onClose} variant="outline" className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary">
            Cerrar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
