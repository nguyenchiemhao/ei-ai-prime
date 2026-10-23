import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import {
  type CollectionDetail,
  type CollectionItem,
  deleteCollection,
  getCollection,
} from "../api/collections";
import { can } from "../api/permissions";
import { useSession } from "../auth/SessionProvider";
import { usePageTitle } from "../components/usePageTitle";
import { AccessBadge } from "../knowledge/AccessBadge";
import { CollectionDialog } from "../knowledge/CollectionDialog";
import { DeleteCollectionDialog } from "../knowledge/DeleteCollectionDialog";
import { DocumentsPanel } from "../knowledge/DocumentsPanel";
import { ALL_DOCUMENTS, FoldersPanel } from "../knowledge/FoldersPanel";
import { knowledgeErrorKey } from "../knowledge/errors";
import { orderAsTree } from "../knowledge/folderTree";
import { areaPath } from "../shell/navigation";
import { useWorkspaceAccess } from "../shell/WorkspaceAccessContext";
import { NotFoundPage } from "./NotFoundPage";
import "../members/members.css";
import "../knowledge/knowledge.css";

const UNAUTHENTICATED = 401;
const NOT_FOUND = 404;
const UNPROCESSABLE = 422;
const ACCESS_PERMISSION = "collections.access.manage";
const KNOWLEDGE_AREA = "knowledge";
const EDIT_MODE = "edit";

/**
 * Knowledge, collection detail (CollectionDetail artboard): access and settings, the folder tree
 * with document counts, the upload drop zone, the document table and the delete action.
 */
export function CollectionDetailPage() {
  const { t } = useTranslation();
  const { itemId = "" } = useParams();
  const navigate = useNavigate();
  const { access } = useWorkspaceAccess();
  const { refresh: refreshSession } = useSession();
  const canManageAccess = can(access, ACCESS_PERMISSION);
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sending, setSending] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  usePageTitle(detail?.name ?? t("admin.knowledge.title"));

  useEffect(() => {
    let cancelled = false;
    void getCollection(access.id, itemId).then((result) => {
      if (cancelled) return;
      if (result.ok) setDetail(result.data);
      else if (result.status === NOT_FOUND || result.status === UNPROCESSABLE) setNotFound(true);
      else if (result.status === UNAUTHENTICATED) void refreshSession();
      else setError(knowledgeErrorKey(result.status, result.code, "collection"));
    });
    return () => {
      cancelled = true;
    };
  }, [access.id, itemId, refreshSession]);

  // Ends the session flow: the shell sends the user to sign in.
  function onSessionExpired() {
    setEditing(false);
    setDeleting(false);
    void refreshSession();
  }

  // A folder request answered 404: show Not found when the collection itself is gone,
  // otherwise refresh the folders (only the folder is gone).
  async function onFolderNotFound() {
    const result = await getCollection(access.id, itemId);
    if (result.ok) setDetail(result.data);
    else if (result.status === NOT_FOUND) setNotFound(true);
  }

  // Reloads the collection to refresh the folder counts after files were uploaded.
  async function refreshFolders() {
    const result = await getCollection(access.id, itemId);
    if (result.ok) {
      setDetail((current) => (current ? { ...current, folders: result.data.folders } : current));
    }
  }

  // Applies the saved collection, keeping the folders, and reports it.
  function onSaved(item: CollectionItem) {
    setDetail((current) => (current ? { ...current, ...item } : current));
    setStatus(t("admin.knowledge.message.saved"));
    setEditing(false);
  }

  // Deletes the collection, then goes back to the list with the confirmation message.
  async function confirmDelete() {
    if (!detail) return;
    setSending(true);
    setDeleteError(null);
    const result = await deleteCollection(access.id, detail.id);
    setSending(false);
    if (result.ok) {
      navigate(areaPath(access.id, KNOWLEDGE_AREA), { state: { deleted: detail.name } });
    } else if (result.status === UNAUTHENTICATED) {
      onSessionExpired();
    } else if (result.status === NOT_FOUND) {
      setNotFound(true);
    } else {
      setDeleteError(knowledgeErrorKey(result.status, result.code, "collection"));
    }
  }

  if (notFound) return <NotFoundPage />;
  if (!detail) {
    return (
      <main className="area-page knowledge-page">
        {error ? (
          <p className="knowledge-alert" role="alert" data-testid="knowledge-error">
            {t(error)}
          </p>
        ) : null}
      </main>
    );
  }

  const selectedFolder = detail.folders.find((item) => item.id === selectedId);
  const defaultFolder = selectedId === ALL_DOCUMENTS ? undefined : orderAsTree(detail.folders)[0];
  const folder = selectedFolder ?? defaultFolder ?? null;

  return (
    <main
      className="area-page knowledge-page"
      data-testid="collection-detail"
      data-collection-id={detail.id}
    >
      <nav className="breadcrumb" aria-label={t("admin.knowledge.detail.breadcrumbLabel")}>
        <Link to={areaPath(access.id, KNOWLEDGE_AREA)}>{t("admin.knowledge.title")}</Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page">{detail.name}</span>
      </nav>
      <header className="knowledge-header">
        <div>
          <h1 className="area-title">{detail.name}</h1>
          {detail.subtitle ? <p className="knowledge-subtitle">{detail.subtitle}</p> : null}
          <div className="collection-badges">
            <AccessBadge level={detail.access_level} groups={detail.groups} />
            <span data-testid="data-handling" className="data-handling-any">
              {detail.local_only ? (
                <span className="local-badge">{t("admin.knowledge.dataHandling.local")}</span>
              ) : (
                t("admin.knowledge.dataHandling.any")
              )}
            </span>
          </div>
        </div>
        <div className="knowledge-header-actions">
          <button
            type="button"
            className="button-secondary"
            data-testid="collection-settings"
            onClick={() => {
              setStatus(null);
              setEditing(true);
            }}
          >
            {t("admin.knowledge.detail.settings")}
          </button>
          <button
            type="button"
            className="button-primary"
            data-testid="upload-files"
            disabled={!folder}
            title={folder ? undefined : t("admin.knowledge.documents.chooseFolder")}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("admin.knowledge.documents.uploadFiles")}
          </button>
        </div>
      </header>
      {status ? (
        <p className="knowledge-status" role="status" data-testid="knowledge-status">
          {status}
        </p>
      ) : null}
      <div className="collection-body">
        <FoldersPanel
          workspaceId={access.id}
          collectionId={detail.id}
          folders={detail.folders}
          selectedId={folder?.id ?? ALL_DOCUMENTS}
          onSelect={setSelectedId}
          onChange={(folders) =>
            setDetail((current) => (current ? { ...current, folders } : current))
          }
          onSessionExpired={onSessionExpired}
          onNotFound={() => void onFolderNotFound()}
        />
        <div className="collection-main">
          <DocumentsPanel
            workspaceId={access.id}
            collectionId={detail.id}
            folder={folder}
            inputRef={fileInputRef}
            onChanged={() => void refreshFolders()}
            onRemoved={(name) =>
              setStatus(t("admin.knowledge.documents.removeDialog.removed", { name }))
            }
            onSessionExpired={onSessionExpired}
          />
        </div>
      </div>
      <section className="danger-row" data-testid="delete-collection-row">
        <div>
          <h2 className="danger-label">{t("admin.knowledge.deleteCollection.label")}</h2>
          <p className="danger-text">{t("admin.knowledge.deleteCollection.consequence")}</p>
        </div>
        <button
          type="button"
          className="button-danger"
          data-testid="delete-collection"
          onClick={() => {
            setDeleteError(null);
            setDeleting(true);
          }}
        >
          {t("admin.knowledge.deleteCollection.button")}
        </button>
      </section>
      {editing ? (
        <CollectionDialog
          mode={EDIT_MODE}
          workspaceId={access.id}
          collection={detail}
          canManageAccess={canManageAccess}
          onClose={() => setEditing(false)}
          onSaved={onSaved}
          onSessionExpired={onSessionExpired}
          onNotFound={() => setNotFound(true)}
        />
      ) : null}
      {deleting ? (
        <DeleteCollectionDialog
          name={detail.name}
          sending={sending}
          error={deleteError}
          onConfirm={() => void confirmDelete()}
          onClose={() => setDeleting(false)}
        />
      ) : null}
    </main>
  );
}
