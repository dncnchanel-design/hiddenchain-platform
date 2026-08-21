/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from "react";
import { loadTrustedContext, type TrustedContext } from "./trusted-space-api";
import { useRemote } from "../../hooks";

type TrustedSpaceContextValue = {
  context: TrustedContext | null;
  loading: boolean;
  refreshing: boolean;
  error: string;
  refreshError: string;
  reload: () => Promise<void>;
};

const TrustedSpaceContext = createContext<TrustedSpaceContextValue | null>(null);

export function TrustedSpaceProvider({ children }: { children: ReactNode }) {
  const remote = useRemote(loadTrustedContext, []);
  return <TrustedSpaceContext.Provider value={{
    context: remote.data,
    loading: remote.loading,
    refreshing: remote.refreshing,
    error: remote.error,
    refreshError: remote.refreshError,
    reload: remote.reload,
  }}>{children}</TrustedSpaceContext.Provider>;
}

export function useTrustedSpaceContext() {
  const context = useContext(TrustedSpaceContext);
  if (!context) throw new Error("useTrustedSpaceContext must be used inside TrustedSpaceProvider");
  return context;
}
