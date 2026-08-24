import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, type AccountSession } from "@/lib/api";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  session: AccountSession | null;
  login: (email: string, password: string) => Promise<void>;
  register: (
    displayName: string,
    email: string,
    password: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [session, setSession] = useState<AccountSession | null>(null);

  useEffect(() => {
    let active = true;
    api.auth
      .me()
      .then((value) => {
        if (!active) return;
        setSession(value);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        setSession(null);
        setStatus("unauthenticated");
      });

    const unauthenticated = () => {
      setSession(null);
      setStatus("unauthenticated");
    };
    window.addEventListener("settra:unauthorized", unauthenticated);
    return () => {
      active = false;
      window.removeEventListener("settra:unauthorized", unauthenticated);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const value = await api.auth.login({ email, password });
    setSession(value);
    setStatus("authenticated");
  }, []);

  const register = useCallback(
    async (displayName: string, email: string, password: string) => {
      const value = await api.auth.register({
        display_name: displayName,
        email,
        password,
      });
      setSession(value);
      setStatus("authenticated");
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      setSession(null);
      setStatus("unauthenticated");
    }
  }, []);

  const value = useMemo(
    () => ({ status, session, login, register, logout }),
    [status, session, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
