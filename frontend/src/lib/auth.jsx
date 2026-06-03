import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("auth_user") || "null");
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  const [adminAll, setAdminAllState] = useState(() => localStorage.getItem("admin_all") === "1");

  const persist = (token, u) => {
    localStorage.setItem("auth_token", token);
    localStorage.setItem("auth_user", JSON.stringify(u));
    setUser(u);
  };

  const fetchMe = useCallback(async () => {
    const token = localStorage.getItem("auth_token");
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      localStorage.setItem("auth_user", JSON.stringify(data.user));
      setUser(data.user);
    } catch {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("auth_user");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    persist(data.token, data.user);
    return data.user;
  };

  const register = async (email, password, name) => {
    const { data } = await api.post("/auth/register", { email, password, name });
    persist(data.token, data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    localStorage.removeItem("admin_all");
    setAdminAllState(false);
    setUser(null);
  };

  const setAdminAll = (v) => {
    if (v) localStorage.setItem("admin_all", "1");
    else localStorage.removeItem("admin_all");
    setAdminAllState(!!v);
  };

  const isAdmin = user?.role === "admin" || user?.email?.startsWith("admin@");
  // Backend returns role for admins; ensure it sticks. (api/auth/me returns role)

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, adminAll, setAdminAll, isAdmin: user?.role === "admin", refresh: fetchMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
