import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken, setUnauthorizedHandler } from "../api/client";
import { authApi } from "../api/endpoints";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  /** True while the stored token is being checked on first load. */
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  isSuperadmin: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => !!getToken());

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Restore the session from a stored token.
  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    authApi
      .me()
      .then((me) => !cancelled && setUser(me))
      .catch(() => !cancelled && setToken(null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await authApi.login(email, password);
      queryClient.clear();
      setToken(res.access_token);
      setUser(res.user);
      return res.user;
    },
    [queryClient],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      logout,
      isSuperadmin: user?.role === "superadmin",
      isAdmin: user?.role === "superadmin" || user?.role === "org_admin",
    }),
    [user, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** The logged-in user; only call this below a route that requires login. */
export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useUser called without a logged-in user");
  return user;
}
