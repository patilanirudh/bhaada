import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, refreshToken, setAccessToken, setLogoutHandler } from "./api";
import type { Owner } from "./types";

type AuthCtx = {
  owner: Owner | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { name: string; email: string; password: string; phone?: string }) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  setOwner: (o: Owner) => void;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [owner, setOwner] = useState<Owner | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const reload = useCallback(async () => {
    setOwner(await api<Owner>("/api/auth/me"));
  }, []);

  useEffect(() => {
    setLogoutHandler(() => {
      setAccessToken(null);
      setOwner(null);
    });
    (async () => {
      const t = await refreshToken();
      if (t) {
        try {
          await reload();
        } catch {
          setOwner(null);
        }
      }
      setLoading(false);
    })();
  }, [reload]);

  const login = async (email: string, password: string) => {
    const r = await api<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
    setAccessToken(r.access_token);
    await reload();
  };

  const register = async (data: { name: string; email: string; password: string; phone?: string }) => {
    const r = await api<{ access_token: string }>("/api/auth/register", { method: "POST", body: data, auth: false });
    setAccessToken(r.access_token);
    await reload();
  };

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST", auth: false });
    } finally {
      setAccessToken(null);
      setOwner(null);
      qc.clear();
    }
  };

  return (
    <Ctx.Provider value={{ owner, loading, login, register, logout, reload, setOwner }}>{children}</Ctx.Provider>
  );
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
