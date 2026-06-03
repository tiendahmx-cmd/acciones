import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Users, Trash, ArrowLeft, Shield } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import { api, fmtNumber } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function AdminUsersPage() {
  const { user, adminAll, setAdminAll } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get("/admin/users");
      setData(res);
    } catch (e) {
      toast.error("No se pudieron cargar los usuarios");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const removeUser = async (id, email) => {
    if (!window.confirm(`¿Eliminar permanentemente a ${email}? Esto borra TODO su contenido.`)) return;
    try {
      await api.delete(`/admin/users/${id}`);
      toast.success(`${email} eliminado`);
      await load();
    } catch (e) {
      toast.error("No se pudo eliminar", { description: e?.response?.data?.detail || e.message });
    }
  };

  return (
    <div className="min-h-screen grain bg-obsidian text-ink-primary">
      <header className="border-b border-line sticky top-0 z-30 backdrop-blur-xl bg-obsidian/80">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/")}
              className="text-ink-secondary hover:text-ink-primary"
              data-testid="back-to-dashboard"
            >
              <ArrowLeft size={16} className="mr-2" /> Dashboard
            </Button>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-brand/15 border border-brand/30">
              <Shield size={14} weight="duotone" className="text-brand" />
              <span className="text-xs uppercase tracking-widest text-brand font-medium">Admin</span>
            </div>
            <h1 className="text-heading text-lg font-semibold tracking-tight">Usuarios</h1>
          </div>

          <label className="flex items-center gap-2 cursor-pointer select-none">
            <span className="text-xs uppercase tracking-widest text-ink-secondary">Ver datos de todos</span>
            <input
              type="checkbox"
              checked={adminAll}
              onChange={(e) => setAdminAll(e.target.checked)}
              data-testid="admin-all-toggle"
              className="w-4 h-4 accent-brand"
            />
          </label>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="rounded-xl border border-line bg-obsidian-surface p-5 mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Users size={20} weight="duotone" className="text-brand" />
            <div>
              <p className="text-heading font-semibold tracking-tight">Total usuarios</p>
              <p className="text-mono text-2xl font-semibold">{data?.count ?? "—"}</p>
            </div>
          </div>
          <Button
            onClick={() => {
              setAdminAll(true);
              toast.info("Vista global activada — todos los datos visibles en el dashboard");
              navigate("/");
            }}
            className="bg-brand hover:bg-brand-hover text-white"
            data-testid="enter-global-view"
          >
            Ver dashboard global
          </Button>
        </div>

        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-20 rounded-lg border border-line bg-obsidian-surface animate-pulse" />
            ))}
          </div>
        ) : (
          <ul className="space-y-2" data-testid="users-list">
            {data?.users?.map((u) => (
              <li
                key={u.id}
                data-testid={`user-${u.id}`}
                className="rounded-xl border border-line bg-obsidian-surface px-4 py-4 hover:bg-obsidian-hover transition-colors"
              >
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex-1 min-w-[200px]">
                    <div className="flex items-center gap-2">
                      <p className="text-heading font-medium text-ink-primary">{u.name || u.email}</p>
                      {u.role === "admin" && (
                        <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded border border-brand/30 bg-brand/10 text-brand">
                          admin
                        </span>
                      )}
                    </div>
                    <p className="text-mono text-xs text-ink-secondary mt-0.5">{u.email}</p>
                    <p className="text-mono text-[10px] text-ink-muted mt-0.5">
                      Registrado: {new Date(u.created_at).toLocaleString("es-MX")}
                    </p>
                  </div>
                  <div className="grid grid-cols-4 gap-3 text-mono text-xs">
                    <Stat label="Watchlist" value={fmtNumber(u.stats.watchlist)} />
                    <Stat label="Lotes" value={fmtNumber(u.stats.lots)} />
                    <Stat label="Trades" value={fmtNumber(u.stats.trades)} />
                    <Stat label="Alertas" value={`${u.stats.unread_alerts}/${u.stats.alerts}`} />
                  </div>
                  {u.id !== user.id && (
                    <button
                      type="button"
                      onClick={() => removeUser(u.id, u.email)}
                      className="w-8 h-8 grid place-items-center rounded-md text-ink-muted hover:bg-bear-soft hover:text-bear transition-colors"
                      data-testid={`delete-user-${u.id}`}
                      title="Eliminar usuario"
                    >
                      <Trash size={14} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="text-center">
      <p className="text-[10px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className="text-ink-primary mt-0.5">{value}</p>
    </div>
  );
}
