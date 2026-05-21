import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Sparkle, TrendUp, TrendDown, Newspaper, ArrowsClockwise } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, fmtUSD, fmtMXN, fmtPct, fmtNumber } from "../lib/api";

const AI_BG = "https://images.unsplash.com/photo-1775057154553-0f3e8902fea3?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDR8MHwxfHNlYXJjaHwxfHxkYXJrJTIwZGF0YSUyMG5ldHdvcmslMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc3ODY5ODk2N3ww&ixlib=rb-4.1.0&q=85";

export default function StockDetailSheet({ ticker, open, onClose, mxnRate }) {
  const [quote, setQuote] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [loadingPred, setLoadingPred] = useState(false);

  useEffect(() => {
    if (!open || !ticker) return;
    setQuote(null);
    setPrediction(null);
    fetchQuote();
    fetchPrediction();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, open]);

  const fetchQuote = async () => {
    setLoadingQuote(true);
    try {
      const { data } = await api.get(`/quote/${ticker}`);
      setQuote(data.quote);
    } catch (e) {
      toast.error("No se pudo cargar la cotización");
    } finally {
      setLoadingQuote(false);
    }
  };

  const fetchPrediction = async () => {
    setLoadingPred(true);
    try {
      const { data } = await api.post(`/predict/${ticker}`);
      setPrediction(data);
    } catch (e) {
      toast.error("Predicción IA no disponible", { description: e?.response?.data?.detail || "" });
    } finally {
      setLoadingPred(false);
    }
  };

  const isUp = (quote?.change_percent ?? 0) >= 0;
  const predUp = prediction?.direction === "up";

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent
        side="right"
        className="bg-obsidian-sheet border-l border-line text-ink-primary p-0 w-full sm:max-w-xl overflow-y-auto scrollbar-thin"
        data-testid="detail-sheet"
      >
        {/* Header with overlay image */}
        <div className="relative overflow-hidden border-b border-line">
          <div
            className="absolute inset-0 opacity-[0.18] bg-cover bg-center"
            style={{ backgroundImage: `url(${AI_BG})` }}
          />
          <div className="absolute inset-0 bg-gradient-to-b from-obsidian-sheet/40 via-obsidian-sheet/70 to-obsidian-sheet" />
          <div className="relative p-6">
            <SheetHeader className="text-left space-y-1">
              <SheetTitle className="text-mono text-2xl font-bold tracking-wider text-ink-primary">
                {ticker}
              </SheetTitle>
              <SheetDescription className="text-ink-secondary">
                {quote?.name || quote?.exchange || "Cargando..."}
              </SheetDescription>
            </SheetHeader>

            {quote && (
              <div className="mt-5 flex items-end justify-between gap-4 flex-wrap">
                <div>
                  <p className="text-mono text-4xl font-semibold tracking-tight">
                    {fmtUSD(quote.price)}
                  </p>
                  <p className="text-mono text-2xl font-medium text-ink-secondary mt-1">
                    {fmtMXN(quote.price_mxn)} <span className="text-ink-muted text-xs">MXN</span>
                  </p>
                </div>
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-mono font-semibold ${
                    isUp
                      ? "text-bull bg-bull-soft border-bull-line"
                      : "text-bear bg-bear-soft border-bear-line"
                  }`}
                >
                  {isUp ? <TrendUp size={14} weight="bold" /> : <TrendDown size={14} weight="bold" />}
                  {fmtPct(quote.change_percent)}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Quote details grid */}
          <section>
            <h3 className="text-xs uppercase tracking-widest text-ink-muted mb-3">Cotización</h3>
            <div className="grid grid-cols-2 gap-3">
              <DetailRow label="Apertura" value={fmtNumber(quote?.open)} />
              <DetailRow label="Máximo" value={fmtNumber(quote?.high)} />
              <DetailRow label="Mínimo" value={fmtNumber(quote?.low)} />
              <DetailRow label="Cierre anterior" value={fmtNumber(quote?.previous_close)} />
              <DetailRow label="Volumen" value={quote?.volume ? quote.volume.toLocaleString("en-US") : "—"} />
              <DetailRow label="USD/MXN" value={mxnRate ? mxnRate.toFixed(4) : "—"} />
            </div>
          </section>

          {/* AI Prediction */}
          <section
            className="rounded-xl border border-brand/30 bg-gradient-to-br from-brand/[0.06] to-transparent p-5 relative overflow-hidden"
            data-testid="ai-prediction-section"
          >
            <div className="absolute -top-12 -right-12 w-40 h-40 rounded-full bg-brand/10 blur-3xl pointer-events-none" />
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Sparkle size={18} weight="fill" className="text-brand" />
                <h3 className="text-heading font-semibold tracking-tight">Predicción IA · Próximo día</h3>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={fetchPrediction}
                disabled={loadingPred}
                data-testid="refresh-prediction"
                className="h-7 px-2 text-ink-secondary hover:text-ink-primary hover:bg-obsidian-hover"
              >
                <ArrowsClockwise size={14} className={loadingPred ? "animate-spin" : ""} />
              </Button>
            </div>

            {loadingPred && !prediction ? (
              <div className="space-y-2">
                <div className="h-8 bg-obsidian-hover rounded animate-pulse" />
                <div className="h-4 bg-obsidian-hover rounded animate-pulse w-3/4" />
                <div className="h-4 bg-obsidian-hover rounded animate-pulse w-1/2" />
              </div>
            ) : prediction ? (
              <div className="space-y-3">
                <div className="flex items-end gap-3 flex-wrap">
                  <p className="text-mono text-3xl font-semibold">
                    {fmtUSD(prediction.prediction_price)}
                  </p>
                  <div
                    className={`text-mono text-sm font-semibold px-2 py-1 rounded-md border ${
                      predUp
                        ? "text-bull bg-bull-soft border-bull-line"
                        : prediction.direction === "down"
                        ? "text-bear bg-bear-soft border-bear-line"
                        : "text-ink-secondary bg-obsidian-hover border-line"
                    }`}
                    data-testid="prediction-change"
                  >
                    {fmtPct(prediction.prediction_change_percent)}
                  </div>
                  <Badge variant="outline" className="border-line bg-obsidian text-ink-secondary capitalize text-xs">
                    confianza {prediction.confidence}
                  </Badge>
                </div>
                <p className="text-sm text-ink-secondary leading-relaxed">
                  {prediction.rationale}
                </p>
              </div>
            ) : (
              <p className="text-sm text-ink-muted">Sin predicción disponible.</p>
            )}
          </section>

          {/* News */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <Newspaper size={18} weight="duotone" className="text-ink-secondary" />
              <h3 className="text-heading font-semibold tracking-tight">Noticias relevantes</h3>
            </div>
            {prediction?.news?.length ? (
              <div className="space-y-3" data-testid="news-list">
                {prediction.news.map((n, i) => (
                  <NewsItem key={i} item={n} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-ink-muted">
                {loadingPred ? "Cargando noticias..." : "No hay noticias disponibles."}
              </p>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function DetailRow({ label, value }) {
  return (
    <div className="rounded-lg border border-line bg-obsidian-surface px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className="text-mono text-sm text-ink-primary mt-1">{value}</p>
    </div>
  );
}

function NewsItem({ item }) {
  const senti = (item.sentiment || "neutral").toLowerCase();
  const sentiCls =
    senti === "positive"
      ? "text-bull border-bull-line bg-bull-soft"
      : senti === "negative"
      ? "text-bear border-bear-line bg-bear-soft"
      : "text-ink-secondary border-line bg-obsidian-hover";
  return (
    <div className="rounded-lg border border-line bg-obsidian-surface p-4 hover:border-line-focus transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-medium text-ink-primary leading-snug">{item.title}</p>
        <span className={`text-[10px] uppercase tracking-widest px-2 py-0.5 rounded border whitespace-nowrap ${sentiCls}`}>
          {senti}
        </span>
      </div>
      <p className="text-xs text-ink-secondary leading-relaxed mb-2">{item.summary}</p>
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{item.source}</p>
    </div>
  );
}
