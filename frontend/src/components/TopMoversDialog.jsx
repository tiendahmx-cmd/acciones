import { useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { TrendUp, TrendDown, Download, Share, ChartLineUp } from "@phosphor-icons/react";
import { toPng } from "html-to-image";
import { toast } from "sonner";
import { fmtUSD, fmtMXN, fmtPct } from "../lib/api";

export default function TopMoversDialog({ open, onOpenChange, quotes, mxnRate }) {
  const cardRef = useRef(null);
  const [busy, setBusy] = useState(false);

  const { winners, losers } = useMemo(() => {
    const valid = quotes.filter((q) => q.change_percent != null);
    const sorted = [...valid].sort((a, b) => b.change_percent - a.change_percent);
    return {
      winners: sorted.slice(0, 3),
      losers: [...sorted].reverse().slice(0, 3),
    };
  }, [quotes]);

  const today = new Date().toLocaleDateString("es-MX", { day: "2-digit", month: "long", year: "numeric" });

  const handleDownload = async () => {
    if (!cardRef.current) return;
    setBusy(true);
    try {
      const dataUrl = await toPng(cardRef.current, {
        cacheBust: true,
        pixelRatio: 2,
        backgroundColor: "#06080A",
      });
      const link = document.createElement("a");
      link.download = `top-movers-${new Date().toISOString().slice(0, 10)}.png`;
      link.href = dataUrl;
      link.click();
      toast.success("Imagen descargada");
    } catch (e) {
      toast.error("No se pudo generar la imagen", { description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleShare = async () => {
    if (!cardRef.current) return;
    setBusy(true);
    try {
      const dataUrl = await toPng(cardRef.current, { cacheBust: true, pixelRatio: 2, backgroundColor: "#06080A" });
      const blob = await (await fetch(dataUrl)).blob();
      const file = new File([blob], "top-movers.png", { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: "Top Movers del día",
          text: `Top movers NASDAQ/NYSE - ${today}`,
        });
        toast.success("Compartido");
      } else {
        toast.info("Tu navegador no soporta compartir archivos. Usa Descargar.");
      }
    } catch (e) {
      if (e.name !== "AbortError") toast.error("No se pudo compartir");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-obsidian-surface border-line text-ink-primary sm:max-w-2xl max-h-[92vh] overflow-y-auto scrollbar-thin"
        data-testid="top-movers-dialog"
      >
        <DialogHeader>
          <DialogTitle className="text-heading font-semibold tracking-tight">Top Movers</DialogTitle>
          <DialogDescription className="text-ink-secondary">
            Resumen visual de tu watchlist en pesos mexicanos. Descarga o comparte la tarjeta.
          </DialogDescription>
        </DialogHeader>

        {/* Shareable card */}
        <div className="overflow-hidden rounded-xl border border-line">
          <div
            ref={cardRef}
            className="bg-obsidian p-8"
            style={{ fontFamily: "IBM Plex Sans, sans-serif" }}
            data-testid="top-movers-card"
          >
            <div className="flex items-start justify-between mb-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-7 h-7 grid place-items-center rounded-md bg-brand/15 border border-brand/30">
                    <ChartLineUp size={14} weight="duotone" color="#3B82F6" />
                  </div>
                  <p className="text-[10px] uppercase tracking-[0.2em] text-ink-secondary">Stock Tracker · MXN</p>
                </div>
                <h2
                  className="text-2xl font-semibold tracking-tight text-ink-primary"
                  style={{ fontFamily: "Manrope, sans-serif" }}
                >
                  Top Movers · {today}
                </h2>
              </div>
              <div className="text-right">
                <p className="text-[10px] uppercase tracking-widest text-ink-muted">USD/MXN</p>
                <p
                  className="text-mono text-base font-semibold text-ink-primary"
                  style={{ fontFamily: "JetBrains Mono, monospace" }}
                >
                  {mxnRate ? mxnRate.toFixed(4) : "—"}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <MoverColumn title="AL ALZA" items={winners} tone="bull" />
              <MoverColumn title="A LA BAJA" items={losers} tone="bear" />
            </div>

            <div className="mt-6 pt-4 border-t border-line flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-widest text-ink-muted">NASDAQ · NYSE</p>
              <p className="text-[10px] uppercase tracking-widest text-ink-muted">
                {new Date().toLocaleTimeString("es-MX")}
              </p>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            variant="outline"
            onClick={handleShare}
            disabled={busy}
            data-testid="share-top-movers"
            className="border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary"
          >
            <Share size={16} weight="bold" className="mr-2" />
            Compartir
          </Button>
          <Button
            onClick={handleDownload}
            disabled={busy}
            data-testid="download-top-movers"
            className="bg-brand hover:bg-brand-hover text-white"
          >
            <Download size={16} weight="bold" className="mr-2" />
            {busy ? "Generando..." : "Descargar PNG"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MoverColumn({ title, items, tone }) {
  const isBull = tone === "bull";
  const Icon = isBull ? TrendUp : TrendDown;
  const color = isBull ? "#10B981" : "#EF4444";
  return (
    <div
      className="rounded-lg p-4"
      style={{
        border: `1px solid ${isBull ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)"}`,
        backgroundColor: isBull ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)",
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} weight="bold" color={color} />
        <p className="text-[10px] uppercase tracking-[0.2em] font-semibold" style={{ color }}>
          {title}
        </p>
      </div>
      <div className="space-y-2.5">
        {items.length === 0 && <p className="text-xs text-ink-muted">Sin datos</p>}
        {items.map((q) => (
          <div key={q.ticker} className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p
                className="text-mono text-sm font-bold tracking-wider text-ink-primary"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {q.ticker}
              </p>
              <p
                className="text-mono text-[11px] text-ink-secondary"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {fmtMXN(q.price_mxn)}
              </p>
            </div>
            <div className="text-right">
              <p
                className="text-mono text-sm text-ink-primary"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {fmtUSD(q.price)}
              </p>
              <p
                className="text-mono text-[11px] font-semibold"
                style={{ color, fontFamily: "JetBrains Mono, monospace" }}
              >
                {fmtPct(q.change_percent)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
