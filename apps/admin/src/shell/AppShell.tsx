import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { type ApiResult } from "../api/client";
import { getWorkspace, type WorkspaceInfo } from "../api/workspaces";
import { useSession } from "../auth/SessionProvider";
import { AreaPage } from "../pages/AreaPage";
import { CollectionDetailPage } from "../pages/CollectionDetailPage";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { KnowledgePage } from "../pages/KnowledgePage";
import { MembersPage } from "../pages/MembersPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { findArea, visibleAreas } from "./navigation";
import { Sidebar } from "./Sidebar";
import { WorkspaceAccessContext } from "./WorkspaceAccessContext";
import "./shell.css";

/** The last answer of the API: for which Workspace and area it was asked. */
interface Answer {
  workspaceId: string;
  area: string | undefined;
  result: ApiResult<WorkspaceInfo>;
}

/**
 * Frame of every `/w/:workspaceId/:area` page. The caller's access is read from the API on every
 * change of Workspace or area (and on `refresh`), so a role change shows from the next click.
 * Nothing of a Workspace (Sidebar, name, role) renders before a 200, and while a new answer is
 * pending the page of the last answer stays.
 */
export function AppShell() {
  const { t } = useTranslation();
  const { refresh: refreshSession } = useSession();
  const { workspaceId = "", area, itemId } = useParams();
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((current) => current + 1), []);

  useEffect(() => {
    let cancelled = false;
    void getWorkspace(workspaceId).then((result) => {
      if (cancelled) return;
      setAnswer({ workspaceId, area, result });
      if (!result.ok && result.status === 401) void refreshSession();
    });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, area, version, refreshSession]);

  const current = answer?.workspaceId === workspaceId ? answer : null;
  const access = current?.result.ok ? current.result.data : null;
  const context = useMemo(() => (access ? { access, refresh } : null), [access, refresh]);

  if (!current) return null;
  if (!current.result.ok) {
    const { status } = current.result;
    if (status === 404 || status === 422) return <NotFoundPage />;
    if (status === 401) return null;
    return (
      <main className="area-page">
        <p className="area-alert" role="alert">
          {t("admin.shell.unavailable")}
        </p>
      </main>
    );
  }
  const shown = findArea(current.area);
  if (!shown || !context) return <NotFoundPage />;
  // Only the Knowledge area has item pages (a collection); any other area + item is not found.
  if (itemId !== undefined && shown.slug !== "knowledge") return <NotFoundPage />;
  const allowed = visibleAreas(context.access.permissions).includes(shown);
  return (
    <WorkspaceAccessContext.Provider value={context}>
      <div className="shell">
        <Sidebar workspace={context.access} area={shown.slug} />
        {!allowed ? (
          <ForbiddenPage />
        ) : shown.slug === "knowledge" ? (
          itemId === undefined ? (
            <KnowledgePage />
          ) : (
            <CollectionDetailPage />
          )
        ) : shown.slug === "members" ? (
          <MembersPage />
        ) : (
          <AreaPage slug={shown.slug} />
        )}
      </div>
    </WorkspaceAccessContext.Provider>
  );
}
