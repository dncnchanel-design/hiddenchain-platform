import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api, invalidateApiCache, post } from "./api";
import type { SessionPayload } from "./types";

interface AuthContextValue {
  session: SessionPayload | null;
  loading: boolean;
  sessionExpired: boolean;
  sessionError: string;
  login: (username: string, password: string) => Promise<SessionPayload>;
  loginWithDid: () => Promise<SessionPayload>;
  logout: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const TOKEN_KEY = "hiddenchain_token";
const WALLET_ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;

type DidLoginChallenge = {
  challenge: string;
  wallet_address: string;
  message: string;
  expires_at: string;
};

type DidLoginResponse = SessionPayload & { access_token: string };

function walletProviderError(reason: unknown): Error {
  if (reason && typeof reason === "object" && "code" in reason && reason.code === 4001) {
    return new Error("你取消了钱包连接或签名");
  }
  return new Error("钱包操作失败，请检查钱包扩展后重试");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [loading, setLoading] = useState(Boolean(sessionStorage.getItem(TOKEN_KEY)));
  const [sessionExpired, setSessionExpired] = useState(false);
  const [sessionError, setSessionError] = useState("");

  const logout = useCallback(async () => {
    let serverLogoutConfirmed = false;
    if (sessionStorage.getItem(TOKEN_KEY)) {
      try {
        await post<void>("/auth/logout", {});
        serverLogoutConfirmed = true;
      } catch {
        // Always clear the local session so a network failure never traps the user.
      }
    }
    sessionStorage.removeItem(TOKEN_KEY);
    invalidateApiCache();
    setSession(null);
    setSessionExpired(false);
    setSessionError("");
    setLoading(false);
    return serverLogoutConfirmed;
  }, []);

  const expireSession = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    invalidateApiCache();
    setSession(null);
    setSessionExpired(true);
    setSessionError("");
    setLoading(false);
  }, []);

  const loadSession = useCallback(async () => {
    if (!sessionStorage.getItem(TOKEN_KEY)) {
      setLoading(false);
      return;
    }
    try {
      setSessionError("");
      setSession(await api<SessionPayload>("/auth/me"));
      setSessionExpired(false);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) expireSession();
      else setSessionError("暂时无法验证会话。有效凭证已保留，请检查服务或网络后重试。");
    } finally {
      setLoading(false);
    }
  }, [expireSession]);

  useEffect(() => {
    localStorage.removeItem(TOKEN_KEY);
    const loadTimer = window.setTimeout(() => void loadSession(), 0);
    window.addEventListener("hiddenchain:unauthorized", expireSession);
    return () => {
      window.clearTimeout(loadTimer);
      window.removeEventListener("hiddenchain:unauthorized", expireSession);
    };
  }, [expireSession, loadSession]);

  const login = useCallback(async (username: string, password: string) => {
    const payload = await post<DidLoginResponse>("/auth/login", { username, password });
    const { access_token: accessToken, ...safeSession } = payload;
    sessionStorage.setItem(TOKEN_KEY, accessToken);
    setSession(safeSession);
    setSessionExpired(false);
    setSessionError("");
    return safeSession;
  }, []);

  const loginWithDid = useCallback(async () => {
    const provider = window.ethereum;
    if (!provider) throw new Error("未检测到浏览器钱包，请安装 MetaMask 后重试");

    let accounts: unknown;
    try {
      accounts = await provider.request({ method: "eth_requestAccounts" });
    } catch (reason) {
      throw walletProviderError(reason);
    }
    const walletAddress = Array.isArray(accounts) && typeof accounts[0] === "string" ? accounts[0] : "";
    if (!WALLET_ADDRESS_PATTERN.test(walletAddress)) throw new Error("钱包没有返回有效地址，请检查钱包账户");

    const challenge = await post<DidLoginChallenge>("/auth/did/challenge", { wallet_address: walletAddress });
    let signature: unknown;
    try {
      signature = await provider.request({ method: "personal_sign", params: [challenge.message, walletAddress] });
    } catch (reason) {
      throw walletProviderError(reason);
    }
    if (typeof signature !== "string" || !signature) throw new Error("钱包未返回有效签名");

    const payload = await post<DidLoginResponse>("/auth/did/verify", {
      challenge: challenge.challenge,
      wallet_address: walletAddress,
      signature,
    });
    const { access_token: accessToken, ...safeSession } = payload;
    sessionStorage.setItem(TOKEN_KEY, accessToken);
    setSession(safeSession);
    setSessionExpired(false);
    setSessionError("");
    return safeSession;
  }, []);

  const value = useMemo(() => ({ session, loading, sessionExpired, sessionError, login, loginWithDid, logout }), [session, loading, sessionExpired, sessionError, login, loginWithDid, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
