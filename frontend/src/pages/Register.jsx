import { useState } from "react";
import { useNavigate, Link, Navigate } from "react-router-dom";
import { ChartLineUp, UserPlus } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { useAuth } from "../lib/auth";

export default function Register() {
  const { register, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    if (password.length < 6) {
      toast.error("La contraseña debe tener al menos 6 caracteres");
      return;
    }
    setBusy(true);
    try {
      await register(email.trim(), password, name.trim() || undefined);
      toast.success("Cuenta creada");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error("No se pudo crear la cuenta", { description: err?.response?.data?.detail || err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grain flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-brand/15 border border-brand/30 mb-4">
            <ChartLineUp size={24} weight="duotone" className="text-brand" />
          </div>
          <h1 className="text-heading text-3xl font-semibold tracking-tight">Crear cuenta</h1>
          <p className="text-sm text-ink-secondary mt-1">Tu watchlist, portafolio y alertas privados</p>
        </div>

        <form onSubmit={submit} className="rounded-xl border border-line bg-obsidian-surface p-6 space-y-4" data-testid="register-form">
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Nombre (opcional)</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Tu nombre"
              className="bg-obsidian border-line mt-1.5 focus-visible:ring-brand"
              data-testid="reg-name"
              maxLength={50}
            />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Email</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@email.com"
              className="bg-obsidian border-line mt-1.5 focus-visible:ring-brand"
              data-testid="reg-email"
              required
              autoFocus
            />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Contraseña (mín 6)</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="bg-obsidian border-line mt-1.5 focus-visible:ring-brand"
              data-testid="reg-password"
              required
              minLength={6}
            />
          </div>

          <Button type="submit" disabled={busy} className="w-full bg-brand hover:bg-brand-hover text-white" data-testid="reg-submit">
            <UserPlus size={16} weight="bold" className="mr-2" />
            {busy ? "Creando..." : "Crear cuenta"}
          </Button>

          <p className="text-sm text-center text-ink-secondary">
            ¿Ya tienes cuenta?{" "}
            <Link to="/login" className="text-brand hover:text-brand-hover" data-testid="link-login">
              Iniciar sesión
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
