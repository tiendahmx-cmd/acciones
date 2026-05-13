import { useEffect, useState, useCallback } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { Button } from "./ui/button";
import { Bell, BellRinging, Trash, Check, TrendUp, TrendDown, ArrowsClockwise } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api } from "../lib/api";

const POLL_MS = 30000;

export default function AlertsBell({ onAlertClick }) {
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [unread, setUnread] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/alerts?limit=50");
      setAlerts(data.alerts || []);
      setUnread(data.unread || 0);
    } catch (e) {
      // silent
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data } = await api.post("/alerts/sync");
      if (data.created > 0) {
        toast.success(`${data.created} nueva${data.created > 1 ? "s" : ""} alerta${data.created > 1 ? "s" : ""}`);
      } else {
        toast.info("Sin nuevos movimientos significativos");
      }
      await load();
    } catch (e) {
      toast.error("No se pudo sincronizar");
    } finally {
      setSyncing(false);
    }
  };

  const markRead = async (id) => {
    await api.post(`/alerts/${id}/read`);
    await load();
  };

  const markAllRead = async () => {
    await api.post("/alerts/read-all");
    await load();
    toast.success("Todas marcadas como leídas");
  };

  const clearAll = async () => {
    await api.delete("/alerts");
    await load();
    toast.success("Alertas limpiadas");
  };

  const BellIcon = unread > 0 ? BellRinging : Bell;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          data-testid="alerts-bell"
          className="relative border-line bg-obsidian-surface hover:bg-obsidian-hover hover:text-ink-primary text-ink-secondary"
        >
          <BellIcon size={16} weight={unread > 0 ? "fill" : "regular"} className={unread > 0 ? "text-brand" : ""} />
          {unread > 0 && (
            <span
              data-testid="alerts-badge"
              className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 grid place-items-center rounded-full bg-brand text-white text-[10px] font-bold text-mono"
            >
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[380px] max-w-[92vw] p-0 bg-obsidian-sheet border-line text-ink-primary"
        data-testid="alerts-panel"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <div>
            <p className="text-heading text-sm font-semibold tracking-tight">Alertas</p>
            <p className="text-xs text-ink-muted">
              {unread > 0 ? `${unread} sin leer` : "Todo al día"}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleSync}
              disabled={syncing}
              data-testid="alerts-sync"
              title="Sincronizar"
              className="w-7 h-7 grid place-items-center rounded-md text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary transition-colors"
            >
              <ArrowsClockwise size={14} className={syncing ? "animate-spin" : ""} />
            </button>
            <button
              type="button"
              onClick={markAllRead}
              disabled={unread === 0}
              data-testid="alerts-read-all"
              title="Marcar todas como leídas"
              className="w-7 h-7 grid place-items-center rounded-md text-ink-secondary hover:bg-obsidian-hover hover:text-ink-primary transition-colors disabled:opacity-30"
            >
              <Check size={14} />
            </button>
            <button
              type="button"
              onClick={clearAll}
              disabled={alerts.length === 0}
              data-testid="alerts-clear"
              title="Limpiar todo"
              className="w-7 h-7 grid place-items-center rounded-md text-ink-secondary hover:bg-bear-soft hover:text-bear transition-colors disabled:opacity-30"
            >
              <Trash size={14} />
            </button>
          </div>
        </div>

        <div className="max-h-[420px] overflow-y-auto scrollbar-thin">
          {alerts.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <Bell size={28} weight="duotone" className="mx-auto text-ink-muted mb-2" />
              <p className="text-sm text-ink-secondary">Sin alertas todavía</p>
              <p className="text-xs text-ink-muted mt-1">
                Movimientos ≥ 3% o cambios de dirección IA aparecerán aquí.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {alerts.map((a) => (
                <AlertItem
                  key={a.id}
                  alert={a}
                  onRead={() => markRead(a.id)}
                  onClick={() => {
                    onAlertClick?.(a.ticker);
                    setOpen(false);
                    if (!a.read) markRead(a.id);
                  }}
                />
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function AlertItem({ alert, onRead, onClick }) {
  const isPrice = alert.type === "price_move";
  const dir = alert.payload?.direction || alert.payload?.to_direction;
  const up = dir === "up";
  const Icon = up ? TrendUp : TrendDown;
  const color = up ? "text-bull" : "text-bear";
  const bg = up ? "bg-bull-soft" : "bg-bear-soft";

  return (
    <li
      data-testid={`alert-item-${alert.id}`}
      className={`px-4 py-3 hover:bg-obsidian-hover transition-colors cursor-pointer ${alert.read ? "opacity-60" : ""}`}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        <div className={`w-8 h-8 grid place-items-center rounded-md ${bg} ${color} shrink-0`}>
          <Icon size={14} weight="bold" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-mono text-xs font-bold tracking-wider">{alert.ticker}</p>
            <span className="text-[9px] uppercase tracking-widest text-ink-muted">
              {isPrice ? "Movimiento" : "Flip IA"}
            </span>
            {!alert.read && <span className="w-1.5 h-1.5 rounded-full bg-brand" />}
          </div>
          <p className="text-sm text-ink-primary leading-snug">{alert.message}</p>
          <p className="text-[10px] text-ink-muted mt-1 text-mono">
            {new Date(alert.created_at).toLocaleString("es-MX", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
        {!alert.read && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onRead();
            }}
            className="w-6 h-6 grid place-items-center rounded-md text-ink-muted hover:bg-obsidian-surface hover:text-ink-primary transition-colors"
            title="Marcar como leída"
          >
            <Check size={12} />
          </button>
        )}
      </div>
    </li>
  );
}
