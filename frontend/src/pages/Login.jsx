import { useState } from "react";
import { useNavigate, Link, Navigate } from "react-router-dom";
import { ChartLineUp, SignIn, Eye, EyeSlash } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email.trim(), password);
      toast.success("Bienvenido");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error("No se pudo iniciar sesión", { description: err?.response?.data?.detail || err.message });
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
          <h1 className="text-heading text-3xl font-semibold tracking-tight">Stock Tracker</h1>
          <p className="text-sm text-ink-secondary mt-1">Inicia sesión para acceder a tu portafolio</p>
        </div>

        <form onSubmit={submit} className="rounded-xl border border-line bg-obsidian-surface p-6 space-y-4" data-testid="login-form">
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Email</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@email.com"
              className="bg-obsidian border-line mt-1.5 focus-visible:ring-brand"
              data-testid="login-email"
              autoFocus
              required
            />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-widest text-ink-muted">Contraseña</Label>
            <div className="relative mt-1.5">
              <Input
                type={show ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="bg-obsidian border-line pr-10 focus-visible:ring-brand"
                data-testid="login-password"
                required
                minLength={6}
              />
              <button
                type="button"
                onClick={() => setShow((s) => !s)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-primary"
                data-testid="toggle-password"
                tabIndex={-1}
              >
                {show ? <EyeSlash size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <Button type="submit" disabled={busy} className="w-full bg-brand hover:bg-brand-hover text-white" data-testid="login-submit">
            <SignIn size={16} weight="bold" className="mr-2" />
            {busy ? "Iniciando..." : "Iniciar sesión"}
          </Button>

          <p className="text-sm text-center text-ink-secondary">
            ¿No tienes cuenta?{" "}
            <Link to="/register" className="text-brand hover:text-brand-hover" data-testid="link-register">
              Crear cuenta
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
