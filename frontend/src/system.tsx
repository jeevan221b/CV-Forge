import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, errorMessage } from "./api";
import type { SystemInfo } from "./types";

interface SystemState {
  system: SystemInfo | null;
  error: string;
  refresh: () => Promise<void>;
}
const Ctx = createContext<SystemState>({ system: null, error: "", refresh: async () => {} });

export function SystemProvider({ children }: { children: ReactNode }) {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      setSystem(await api.system());
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return <Ctx.Provider value={{ system, error, refresh }}>{children}</Ctx.Provider>;
}

export const useSystem = () => useContext(Ctx);
