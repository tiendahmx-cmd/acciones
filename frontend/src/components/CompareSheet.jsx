import { useEffect, useMemo, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Button } from "./ui/button";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";
import { toast } from "sonner";
import { Scales, TrendUp, TrendDown } from "@phosphor-icons/react";
import { api } from "../lib/api";

const COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#A78BFA"];

export default function CompareSheet({ open, onClose, tickers, available }) {
  const [selected, setSelected] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setSelected(tickers && tickers.length >= 2 ? tickers.slice(0, 2) : []);
      setData(null);
    }
  }, [open, tickers]);

  useEffect(() => {
    if (!open || selected.length < 2) return;
    const load = async () => {
      setLoading(true);
      try {
        const { data: res } = await api.get(`/compare?tickers=${selected.join(",")}`);
        setData(res);
      } catch (e) {
        toast.error("No se pudo comparar", { description: e?.response?.data?.detail || e.message });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [selected, open]);

  const toggle = (t) => {
    setSelected((prev) => {
      if (prev.includes(t)) return prev.filter((x) => x !== t);
      if (prev.length >= 4) return prev;
      return [...prev, t];
    });
  };

  const chartData = useMemo(() => {
    if (!data?.series?.length) return [];
    const byDate = {};
    data.series.forEach((s) => {
      s.points.forEach((p) => {
        if (!byDate[p.date]) byDate[p.date] = { date: p.date };
        byDate[p.date][s.ticker] = p.value;
      });
    });
    return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
  }, [data]);

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent
        side="right"
        className="bg-obsidian-sheet border-l border-line text-ink-primary p-0 w-full sm:max-w-2xl overflow-y-auto scrollbar-thin"
        data-testid="compare-sheet"
      >
        <SheetHeader className="p-6 border-b border-line text-left">
          <div className="flex items-center gap-2">
            <Scales size={20} weight="duotone" className="text-brand" />
            <SheetTitle className="text-heading font-semibold tracking-tight">Comparar tickers</SheetTitle>
          </div>
          <SheetDescription className="text-ink-secondary">
            Selecciona 2 a 4 símbolos. Rendimiento normalizado a base 100 en los últimos 30 días.
          </SheetDescription>
        </SheetHeader>

        <div className="p-6 space-y-6">
          <div>
            <p className="text-xs uppercase tracking-widest text-ink-muted mb-3">Seleccionados ({selected.length}/4)</p>
            <div className="flex flex-wrap gap-2">
              {available.map((t) => {
                const active = selected.includes(t);
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => toggle(t)}
                    data-testid={`compare-toggle-${t}`}
                    className={`text-mono text-xs px-3 py-1.5 rounded-md border transition-colors ${
                      active
                        ? "border-brand bg-brand/15 text-brand"
                        : "border-line bg-obsidian text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary"
                    }`}
                  >
                    {t}
                  </button>
                );
              })}
            </div>
          </div>

          {selected.length < 2 ? (
            <div className="rounded-xl border border-dashed border-line p-10 text-center text-sm text-ink-secondary">
              Selecciona al menos 2 tickers para comparar.
            </div>
          ) : loading ? (
            <div className="h-72 rounded-xl border border-line bg-obsidian-surface animate-pulse" />
          ) : data ? (
            <>
              <div className="rounded-xl border border-line bg-obsidian-surface p-4">
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <CartesianGrid stroke="#1E232B" strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="date"
                        stroke="#475569"
                        tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                        tickFormatter={(d) => d?.slice(5)}
                        minTickGap={28}
                      />
                      <YAxis
                        stroke="#475569"
                        tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                        domain={["auto", "auto"]}
                        tickFormatter={(v) => v.toFixed(0)}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#0E1116",
                          border: "1px solid #1E232B",
                          borderRadius: 8,
                          fontFamily: "JetBrains Mono",
                          fontSize: 12,
                        }}
                        labelStyle={{ color: "#94A3B8" }}
                      />
                      <Legend wrapperStyle={{ fontFamily: "JetBrains Mono", fontSize: 12 }} />
                      {data.series.map((s, i) => (
                        <Line
                          key={s.ticker}
                          type="monotone"
                          dataKey={s.ticker}
                          stroke={COLORS[i % COLORS.length]}
                          strokeWidth={2}
                          dot={false}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {data.series.map((s, i) => {
                  const up = s.change_percent >= 0;
                  return (
                    <div key={s.ticker} className="rounded-lg border border-line bg-obsidian-surface p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                          <p className="text-mono font-bold tracking-wider">{s.ticker}</p>
                        </div>
                        <div
                          className={`flex items-center gap-1 text-mono text-xs font-semibold ${
                            up ? "text-bull" : "text-bear"
                          }`}
                        >
                          {up ? <TrendUp size={12} weight="bold" /> : <TrendDown size={12} weight="bold" />}
                          {up ? "+" : ""}
                          {s.change_percent.toFixed(2)}%
                        </div>
                      </div>
                      <p className="text-xs text-ink-muted mt-2 text-mono">
                        ${s.start.toFixed(2)} → ${s.end.toFixed(2)} <span className="text-ink-muted">(30d)</span>
                      </p>
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}

          <Button
            variant="outline"
            onClick={onClose}
            className="w-full border-line bg-transparent text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary"
            data-testid="close-compare"
          >
            Cerrar
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
