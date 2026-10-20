import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { PATHS } from "../paths";
import { useSession } from "./SessionProvider";

/** Renders children for a signed-in user, sends everyone else to /sign-in. */
export function RequireSession({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  if (loading) return null;
  if (!session) return <Navigate to={PATHS.signIn} replace />;
  return <>{children}</>;
}
