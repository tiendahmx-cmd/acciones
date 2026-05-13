import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Plus } from "@phosphor-icons/react";

const SUGGESTIONS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "AMD", "NFLX", "SPY", "QQQ"];

export default function AddStockDialog({ open, onOpenChange, onAdd }) {
  const [ticker, setTicker] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e) => {
    e?.preventDefault();
    if (!ticker.trim()) return;
    setSubmitting(true);
    await onAdd(ticker.trim().toUpperCase());
    setSubmitting(false);
    setTicker("");
  };

  const quickAdd = async (t) => {
    setSubmitting(true);
    await onAdd(t);
    setSubmitting(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-obsidian-surface border-line text-ink-primary sm:max-w-md"
        data-testid="add-stock-dialog"
      >
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight">
            Añadir símbolo
          </DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Ingresa un ticker de NASDAQ o NYSE (ej: NVDA, AAPL).
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <Input
            autoFocus
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="NVDA"
            className="bg-obsidian border-line text-mono tracking-widest uppercase placeholder:text-ink-muted focus-visible:ring-brand"
            data-testid="ticker-input"
            maxLength={10}
          />

          <div>
            <p className="text-xs uppercase tracking-widest text-ink-muted mb-2">Sugerencias</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  type="button"
                  key={s}
                  onClick={() => quickAdd(s)}
                  disabled={submitting}
                  data-testid={`suggestion-${s}`}
                  className="text-mono text-xs px-3 py-1.5 rounded-md border border-line bg-obsidian text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary hover:border-line-focus transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary"
              onClick={() => onOpenChange(false)}
              data-testid="cancel-add"
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              disabled={submitting || !ticker.trim()}
              className="bg-brand hover:bg-brand-hover text-white"
              data-testid="confirm-add"
            >
              <Plus size={16} weight="bold" className="mr-2" />
              {submitting ? "Añadiendo..." : "Añadir"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
