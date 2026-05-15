import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Button } from "./ui/button";
import { CashRegister, X } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, fmtUSD, fmtMXN, fmtNumber, fmtPct } from "../lib/api";

const METHODS = [
  { value: "FIFO", label: "FIFO", desc: "Primero comprado, primero vendido" },
  { value: "LIFO", label: "LIFO", desc: "Último comprado, primero vendido" },
  { value: "SPECIFIC", label: "Específico", desc: "Yo elijo qué lotes" },
];

export default function SellPositionDialog({ position, open, onClose, onSold, defaultRate }) {
  const ticker = position?.ticker;
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [fx, setFx] = useState("");
  const [date, setDate] = useState("");
  const [method, setMethod] = useState("FIFO");
  const [lots, setLots] = useState([]);
  const [selectedLots, setSelectedLots] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !ticker) return;
    setQty("");
    setPrice(position?.current_price ? position.current_price.toFixed(2) : "");
    setFx(defaultRate ? defaultRate.toFixed(4) : "");
    setDate(new Date().toISOString().slice(0, 10));
    setMethod("FIFO");
    setSelectedLots([]);
    api.get(`/portfolio/lots/${ticker}`).then(({ data }) => {
      setLots(data.lots || []);
    });
  }, [open, ticker, defaultRate, position?.current_price]);

  const sortedLots = useMemo(() => {
    if (method === "FIFO") return [...lots].sort((a, b) => (a.buy_date || "").localeCompare(b.buy_date || ""));
    if (method === "LIFO") return [...lots].sort((a, b) => (b.buy_date || "").localeCompare(a.buy_date || ""));
    return lots;
  }, [lots, method]);

  const projection = useMemo(() => {
    const q = parseFloat(qty);
    const p = parseFloat(price);
    if (!q || !p || !position?.avg_cost_usd) return null;
    const pnl_usd = (p - position.avg_cost_usd) * q;
    const pct = ((p - position.avg_cost_usd) / position.avg_cost_usd) * 100;
    const proceedsMxn = fx ? p * q * parseFloat(fx) : null;
    const costMxn = position.avg_cost_mxn * q;
    const pnl_mxn = proceedsMxn != null ? proceedsMxn - costMxn : null;
    return { pnl_usd, pct, pnl_mxn };
  }, [qty, price, fx, position]);

  const submit = async (e) => {
    e?.preventDefault();
    if (!qty || !price) return;
    setBusy(true);
    try {
      const body = {
        ticker,
        qty: parseFloat(qty),
        sell_price_usd: parseFloat(price),
        sell_fx_rate: fx ? parseFloat(fx) : undefined,
        sell_date: date,
        method,
      };
      if (method === "SPECIFIC") {
        if (selectedLots.length === 0) {
          toast.error("Selecciona al menos un lote");
          setBusy(false);
          return;
        }
        body.lot_ids = selectedLots;
      }
      const { data } = await api.post("/portfolio/sell", body);
      toast.success(`Venta cerrada · ${fmtUSD(data.pnl_usd)} P&L (${fmtPct(data.return_pct)})`);
      onSold?.();
    } catch (err) {
      toast.error("No se pudo registrar la venta", { description: err?.response?.data?.detail || err.message });
    } finally {
      setBusy(false);
    }
  };

  const toggleLot = (id) => {
    setSelectedLots((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const maxQty = position?.qty || 0;
  const setMax = () => setQty(String(maxQty));

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-obsidian-surface border-line text-ink-primary sm:max-w-lg max-h-[92vh] overflow-y-auto scrollbar-thin" data-testid="sell-dialog">
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight flex items-center gap-2">
            <CashRegister size={18} weight="duotone" className="text-brand" /> Vender {ticker}
          </DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Posición actual: <span className="text-mono text-ink-primary">{fmtNumber(maxQty)} sh</span> · costo promedio {fmtUSD(position?.avg_cost_usd)}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="flex items-center justify-between">
                <Label className="text-xs uppercase tracking-widest text-ink-muted">Cantidad</Label>
                <button type="button" onClick={setMax} className="text-[10px] uppercase tracking-widest text-brand hover:text-brand-hover">
                  Vender todo
                </button>
              </div>
              <Input
                type="number"
                step="0.0001"
                min="0"
                max={maxQty}
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                placeholder={String(maxQty)}
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="sell-qty"
                required
              />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">Precio venta USD</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="230.00"
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="sell-price"
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
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="sell-fx"
              />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-widest text-ink-muted">Fecha</Label>
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="bg-obsidian border-line text-mono mt-1.5 focus-visible:ring-brand"
                data-testid="sell-date"
              />
            </div>
          </div>

          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Método de asignación</Label>
            <div className="grid grid-cols-3 gap-2 mt-1.5" data-testid="sell-method">
              {METHODS.map((m) => (
                <button
                  type="button"
                  key={m.value}
                  onClick={() => setMethod(m.value)}
                  data-testid={`method-${m.value}`}
                  className={`px-3 py-2 rounded-md border text-xs transition-colors ${
                    method === m.value
                      ? "border-brand bg-brand/15 text-brand"
                      : "border-line bg-obsidian text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary"
                  }`}
                  title={m.desc}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-ink-muted mt-1.5">
              {METHODS.find((m) => m.value === method)?.desc}
            </p>
          </div>

          {method === "SPECIFIC" && (
            <div className="rounded-lg border border-line bg-obsidian p-3" data-testid="lot-selector">
              <p className="text-xs uppercase tracking-widest text-ink-muted mb-2">Selecciona lotes (orden importa)</p>
              <ul className="space-y-1.5 max-h-40 overflow-y-auto scrollbar-thin">
                {sortedLots.map((lot) => {
                  const checked = selectedLots.includes(lot.id);
                  return (
                    <li key={lot.id}>
                      <label className="flex items-center gap-3 px-2 py-1.5 rounded-md hover:bg-obsidian-hover cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleLot(lot.id)}
                          data-testid={`select-lot-${lot.id}`}
                          className="w-3.5 h-3.5 rounded accent-brand"
                        />
                        <div className="flex-1 grid grid-cols-3 gap-2 text-mono text-xs">
                          <span className="text-ink-secondary">{lot.buy_date}</span>
                          <span className="text-ink-primary">{fmtNumber(lot.qty)} sh</span>
                          <span className="text-ink-secondary text-right">{fmtUSD(lot.buy_price_usd)}</span>
                        </div>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {projection && (
            <div className="rounded-lg border border-line bg-obsidian-hover p-3 grid grid-cols-3 gap-2 text-xs" data-testid="sell-projection">
              <Stat label="P&L USD" value={fmtUSD(projection.pnl_usd)} tone={projection.pnl_usd >= 0 ? "bull" : "bear"} />
              <Stat label="P&L MXN" value={projection.pnl_mxn != null ? fmtMXN(projection.pnl_mxn) : "—"} tone={(projection.pnl_mxn ?? 0) >= 0 ? "bull" : "bear"} />
              <Stat label="Retorno" value={fmtPct(projection.pct)} tone={projection.pct >= 0 ? "bull" : "bear"} />
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={onClose} className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary">
              Cancelar
            </Button>
            <Button type="submit" disabled={busy} className="bg-brand hover:bg-brand-hover text-white" data-testid="confirm-sell">
              {busy ? "Procesando..." : "Cerrar operación"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value, tone }) {
  const cls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-primary";
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className={`text-mono text-sm mt-1 ${cls}`}>{value}</p>
    </div>
  );
}
