import type { ReactNode } from "react";
import { Navigate, Outlet, type RouteObject } from "react-router";
import { RequireSession } from "./auth/RequireSession";
import { SessionProvider, useSession } from "./auth/SessionProvider";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { NoWorkspacePage } from "./pages/NoWorkspacePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SetPasswordPage } from "./pages/SetPasswordPage";
import { SignInPage } from "./pages/SignInPage";
import { homePath, PATHS } from "./paths";
import { AppShell } from "./shell/AppShell";

function RootRedirect() {
  const { session, loading } = useSession();
  if (loading) return null;
  return <Navigate to={session ? homePath(session.default_workspace_id) : PATHS.signIn} replace />;
}

/** Public pages (sign-in) send signed-in visitors to their home. */
function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { session, loading } = useSession();
  if (loading) return null;
  if (session) return <Navigate to={homePath(session.default_workspace_id)} replace />;
  return <>{children}</>;
}

export const routes: RouteObject[] = [
  {
    element: (
      <SessionProvider>
        <Outlet />
      </SessionProvider>
    ),
    children: [
      { path: PATHS.root, element: <RootRedirect /> },
      {
        path: PATHS.signIn,
        element: (
          <RedirectIfSignedIn>
            <SignInPage />
          </RedirectIfSignedIn>
        ),
      },
      { path: PATHS.forgotPassword, element: <ForgotPasswordPage /> },
      { path: PATHS.setPassword, element: <SetPasswordPage /> },
      { path: PATHS.reset, element: <SetPasswordPage /> },
      {
        path: PATHS.noWorkspace,
        element: (
          <RequireSession>
            <NoWorkspacePage />
          </RequireSession>
        ),
      },
      {
        path: PATHS.workspaceArea,
        element: (
          <RequireSession>
            <AppShell />
          </RequireSession>
        ),
      },
      { path: PATHS.notFound, element: <NotFoundPage /> },
    ],
  },
];
