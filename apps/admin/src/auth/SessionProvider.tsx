import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { getSession, type SessionInfo, signOut as signOutRequest } from "../api/auth";

export interface SessionState {
  session: SessionInfo | null;
  loading: boolean;
  refresh(): Promise<void>;
  signOut(): Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

async function loadSession(): Promise<SessionInfo | null> {
  const result = await getSession();
  return result.ok ? result.data : null;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setSession(await loadSession());
    setLoading(false);
  }, []);

  const signOut = useCallback(async () => {
    await signOutRequest();
    setSession(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void loadSession().then((loaded) => {
      if (cancelled) return;
      setSession(loaded);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <SessionContext.Provider value={{ session, loading, refresh, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
