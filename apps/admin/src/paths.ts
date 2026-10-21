/** Route paths of the admin console (not user-facing text). */
export const PATHS = {
  root: "/",
  signIn: "/sign-in",
  forgotPassword: "/forgot-password",
  setPassword: "/set-password",
  reset: "/reset",
  noWorkspace: "/no-workspace",
  workspaceArea: "/w/:workspaceId/:area",
  workspaceItem: "/w/:workspaceId/:area/:itemId",
  notFound: "*",
} as const;

/** Where a signed-in user lands: the Dashboard of the default Workspace, or the no-Workspace page. */
export function homePath(defaultWorkspaceId: string | null): string {
  return defaultWorkspaceId ? `/w/${defaultWorkspaceId}/dashboard` : PATHS.noWorkspace;
}
