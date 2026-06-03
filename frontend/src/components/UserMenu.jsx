import { useNavigate } from "react-router-dom";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { User, SignOut, Shield, Eye, EyeSlash, Users } from "@phosphor-icons/react";
import { useAuth } from "../lib/auth";
import { toast } from "sonner";

export default function UserMenu() {
  const { user, logout, isAdmin, adminAll, setAdminAll } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  const initials = (user.name || user.email).slice(0, 2).toUpperCase();

  const onLogout = () => {
    logout();
    toast.success("Sesión cerrada");
    navigate("/login", { replace: true });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="user-menu"
          className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-colors ${
            isAdmin && adminAll
              ? "border-brand/40 bg-brand/10 text-brand"
              : "border-line bg-obsidian-surface hover:bg-obsidian-hover text-ink-secondary"
          }`}
        >
          <div className="w-7 h-7 grid place-items-center rounded-full bg-brand/15 text-brand text-mono text-xs font-bold">
            {initials}
          </div>
          <span className="hidden sm:inline text-xs text-mono">{user.name || user.email.split("@")[0]}</span>
          {isAdmin && (
            <span className="hidden sm:inline-flex items-center gap-1 text-[10px] uppercase tracking-widest text-brand">
              <Shield size={10} weight="bold" />
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-0 bg-obsidian-sheet border-line text-ink-primary" data-testid="user-popover">
        <div className="px-4 py-3 border-b border-line">
          <div className="flex items-center gap-2">
            <User size={14} weight="bold" className="text-ink-secondary" />
            <p className="text-heading text-sm font-semibold truncate">{user.name || "Usuario"}</p>
          </div>
          <p className="text-xs text-ink-secondary mt-0.5 truncate">{user.email}</p>
          {isAdmin && (
            <p className="text-[10px] uppercase tracking-widest text-brand mt-1 flex items-center gap-1">
              <Shield size={10} weight="bold" /> Administrador
            </p>
          )}
        </div>

        {isAdmin && (
          <div className="px-4 py-3 border-b border-line space-y-2">
            <label className="flex items-center justify-between gap-2 cursor-pointer">
              <span className="flex items-center gap-2 text-xs text-ink-secondary">
                {adminAll ? <Eye size={14} weight="duotone" className="text-brand" /> : <EyeSlash size={14} />}
                Vista global
              </span>
              <input
                type="checkbox"
                checked={adminAll}
                onChange={(e) => setAdminAll(e.target.checked)}
                data-testid="admin-all-switch"
                className="w-4 h-4 accent-brand"
              />
            </label>
            <button
              type="button"
              onClick={() => navigate("/admin/users")}
              data-testid="goto-admin-users"
              className="w-full text-left text-xs text-ink-secondary hover:text-ink-primary flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-obsidian-hover"
            >
              <Users size={14} /> Gestionar usuarios
            </button>
          </div>
        )}

        <button
          type="button"
          onClick={onLogout}
          data-testid="logout-btn"
          className="w-full text-left text-sm text-ink-secondary hover:text-bear hover:bg-bear-soft px-4 py-3 flex items-center gap-2 transition-colors"
        >
          <SignOut size={14} weight="bold" />
          Cerrar sesión
        </button>
      </PopoverContent>
    </Popover>
  );
}
