import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, post } from "./api";
import type { SessionPayload } from "./types";

interface AuthContextValue {
  session: SessionPayload | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [loading, setLoading] = useState(Boolean(localStorage.getItem("hiddenchain_token")));

  const logout = useCallback(() => {
    localStorage.removeItem("hiddenchain_token");
    setSession(null);
    setLoading(false);
  }, []);

  const loadSession = useCallback(async () => {
    if (!localStorage.getItem("hiddenchain_token")) {
      setLoading(false);
      return;
    }
    try {
      setSession(await api<SessionPayload>("/auth/me"));
    } catch {
      logout();
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    void loadSession();
    window.addEventListener("hiddenchain:unauthorized", logout);
    return () => window.removeEventListener("hiddenchain:unauthorized", logout);
  }, [loadSession, logout]);

  const login = useCallback(async (username: string, password: string) => {
    const payload = await post<SessionPayload & { access_token: string }>("/auth/login", { username, password });
    localStorage.setItem("hiddenchain_token", payload.access_token);
    setSession(payload);
  }, []);

  const value = useMemo(() => ({ session, loading, login, logout }), [session, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
