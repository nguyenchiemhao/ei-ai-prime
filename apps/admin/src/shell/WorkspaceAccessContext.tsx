import { createContext, useContext } from "react";
import type { WorkspaceInfo } from "../api/workspaces";

export interface WorkspaceAccessState {
  /** The caller's roles and permissions in the current Workspace, as the API last answered. */
  access: WorkspaceInfo;
  /** Ask the API again (after the caller changed their own role). */
  refresh(): void;
}

export const WorkspaceAccessContext = createContext<WorkspaceAccessState | null>(null);

export function useWorkspaceAccess(): WorkspaceAccessState {
  const value = useContext(WorkspaceAccessContext);
  if (!value) throw new Error("useWorkspaceAccess must be used inside the AppShell");
  return value;
}
