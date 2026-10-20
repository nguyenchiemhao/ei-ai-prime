import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { type ApiResult } from "../api/client";
import { getWorkspace, type WorkspaceAccess } from "../api/workspaces";
import { useSession } from "../auth/SessionProvider";
import { AreaPage } from "../pages/AreaPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { findArea } from "./navigation";
import { Sidebar } from "./Sidebar";
import "./shell.css";

interface Check {
  workspaceId: string;
  result: ApiResult<WorkspaceAccess>;
}

/**
 * Frame of every `/w/:workspaceId/:area` page. The Workspace is checked with the API on each
 * change of the id; nothing of it (Sidebar, name, role) renders before a 200.
 */
export function AppShell() {
  const { t } = useTranslation();
  const { refresh } = useSession();
  const { workspaceId = "", area } = useParams();
  const [check, setCheck] = useState<Check | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getWorkspace(workspaceId).then((result) => {
      if (cancelled) return;
      setCheck({ workspaceId, result });
      if (!result.ok && result.status === 401) void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, refresh]);

  const known = findArea(area);
  const result = check?.workspaceId === workspaceId ? check.result : null;
  if (!result) return null;
  if (!result.ok) {
    if (result.status === 404 || result.status === 422) return <NotFoundPage />;
    if (result.status === 401) return null;
    return (
      <main className="area-page">
        <p className="area-alert" role="alert">
          {t("admin.shell.unavailable")}
        </p>
      </main>
    );
  }
  if (!known) return <NotFoundPage />;
  return (
    <div className="shell">
      <Sidebar workspace={result.data} area={known.slug} />
      <AreaPage slug={known.slug} />
    </div>
  );
}
