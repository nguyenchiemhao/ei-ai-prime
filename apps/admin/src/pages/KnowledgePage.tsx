import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import { type CollectionItem, listCollections } from "../api/collections";
import { useSession } from "../auth/SessionProvider";
import { usePageTitle } from "../components/usePageTitle";
import { can } from "../api/permissions";
import { AccessLegend } from "../knowledge/AccessLegend";
import { CollectionDialog } from "../knowledge/CollectionDialog";
import { CollectionsTable } from "../knowledge/CollectionsTable";
import { knowledgeErrorKey } from "../knowledge/errors";
import { matchesSearch } from "../knowledge/labels";
import { useWorkspaceAccess } from "../shell/WorkspaceAccessContext";
import "../members/members.css";
import "../knowledge/knowledge.css";

const UNAUTHENTICATED = 401;
const CREATE_MODE = "create";
const ACCESS_PERMISSION = "collections.access.manage";

/**
 * Knowledge, Collections list (Collections artboard): who can read each collection, how its data
 * is handled, and a search. The API checks every permission again; this page only shows state.
 */
export function KnowledgePage() {
  const { t } = useTranslation();
  const { access } = useWorkspaceAccess();
  const { refresh: refreshSession } = useSession();
  const canManageAccess = can(access, ACCESS_PERMISSION);
  usePageTitle(t("admin.knowledge.title"));
  const [collections, setCollections] = useState<CollectionItem[] | null>(null);
  const location = useLocation();
  const deletedName = (location.state as { deleted?: unknown } | null)?.deleted;
  const [status, setStatus] = useState<string | null>(() =>
    typeof deletedName === "string"
      ? t("admin.knowledge.message.deleted", { name: deletedName })
      : null,
  );
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    void listCollections(access.id).then((result) => {
      if (cancelled) return;
      if (result.ok) setCollections(result.data);
      else if (result.status === UNAUTHENTICATED) void refreshSession();
      else setError(t(knowledgeErrorKey(result.status, result.code, "collection")));
    });
    return () => {
      cancelled = true;
    };
  }, [access.id, t, refreshSession]);

  // Opens the create dialog and clears the previous message.
  function onCreate() {
    setStatus(null);
    setError(null);
    setCreating(true);
  }

  // Adds the created collection to the list, keeping the name order, and reports it.
  function onCreated(item: CollectionItem) {
    setCollections((current) =>
      [...(current ?? []), item].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      ),
    );
    setStatus(t("admin.knowledge.message.created", { name: item.name }));
    setCreating(false);
  }

  // Ends the session flow: the shell sends the user to sign in.
  function onSessionExpired() {
    setCreating(false);
    void refreshSession();
  }

  const visible = (collections ?? []).filter((item) => matchesSearch(item, query));
  const isEmpty = collections !== null && collections.length === 0;

  return (
    <main className="area-page knowledge-page" data-testid="knowledge-page">
      <header className="knowledge-header">
        <div>
          <h1 className="area-title">{t("admin.knowledge.title")}</h1>
          <p className="knowledge-subtitle">{t("admin.knowledge.subtitle")}</p>
        </div>
        {collections !== null && !isEmpty ? (
          <button
            type="button"
            className="button-primary"
            data-testid="new-collection"
            onClick={onCreate}
          >
            {t("admin.knowledge.new")}
          </button>
        ) : null}
      </header>
      {status ? (
        <p className="knowledge-status" role="status" data-testid="knowledge-status">
          {status}
        </p>
      ) : null}
      {error ? (
        <p className="knowledge-alert" role="alert" data-testid="knowledge-error">
          {error}
        </p>
      ) : null}
      <AccessLegend />
      {isEmpty ? (
        <section className="knowledge-card knowledge-empty" data-testid="collections-empty">
          <h2 className="knowledge-empty-title">{t("admin.knowledge.empty.title")}</h2>
          <p>{t("admin.knowledge.empty.text")}</p>
          <button
            type="button"
            className="button-primary"
            data-testid="new-collection"
            onClick={onCreate}
          >
            {t("admin.knowledge.new")}
          </button>
        </section>
      ) : null}
      {collections !== null && !isEmpty ? (
        <section className="knowledge-card">
          <div className="knowledge-toolbar">
            <input
              type="text"
              className="knowledge-search"
              data-testid="collections-search"
              name="search"
              aria-label={t("admin.knowledge.search")}
              placeholder={t("admin.knowledge.search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          {visible.length > 0 ? (
            <CollectionsTable workspaceId={access.id} collections={visible} />
          ) : (
            <p className="knowledge-no-match" data-testid="collections-no-match">
              {t("admin.knowledge.noMatch")}
            </p>
          )}
        </section>
      ) : null}
      <p className="knowledge-footnote" data-testid="collections-footnote">
        {t("admin.knowledge.footnote")}
      </p>
      {creating ? (
        <CollectionDialog
          mode={CREATE_MODE}
          workspaceId={access.id}
          canManageAccess={canManageAccess}
          onClose={() => setCreating(false)}
          onSaved={onCreated}
          onSessionExpired={onSessionExpired}
        />
      ) : null}
    </main>
  );
}
