import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { CollectionItem } from "../api/collections";
import { collectionPath } from "../shell/navigation";
import { AccessBadge } from "./AccessBadge";

interface Props {
  workspaceId: string;
  collections: readonly CollectionItem[];
}

function StatusText({ item }: { item: CollectionItem }) {
  const { t } = useTranslation();
  const { total, processing, needs_attention: needsAttention } = item.documents;
  if (total === 0) return <>{t("admin.knowledge.status.none")}</>;
  if (needsAttention > 0) {
    return <>{t("admin.knowledge.status.needsAttention", { count: needsAttention })}</>;
  }
  if (processing > 0) return <>{t("admin.knowledge.status.processing", { count: processing })}</>;
  return <>{t("admin.knowledge.status.ready")}</>;
}

/** The Collections table (Collections artboard). */
export function CollectionsTable({ workspaceId, collections }: Props) {
  const { t } = useTranslation();
  return (
    <div className="knowledge-scroll">
      <table
        className="knowledge-table"
        data-testid="collections-table"
        aria-label={t("admin.knowledge.tableLabel")}
      >
        <thead>
          <tr>
            <th scope="col">{t("admin.knowledge.column.collection")}</th>
            <th scope="col">{t("admin.knowledge.column.access")}</th>
            <th scope="col">{t("admin.knowledge.column.dataHandling")}</th>
            <th scope="col">{t("admin.knowledge.column.documents")}</th>
            <th scope="col">{t("admin.knowledge.column.status")}</th>
            <th scope="col">{t("admin.knowledge.column.usedBy")}</th>
          </tr>
        </thead>
        <tbody>
          {collections.map((item) => (
            <tr key={item.id} data-testid="collection-row" data-collection-id={item.id}>
              <td>
                <Link className="collection-link" to={collectionPath(workspaceId, item.id)}>
                  {item.name}
                </Link>
                {item.subtitle ? <div className="collection-meta">{item.subtitle}</div> : null}
              </td>
              <td>
                <AccessBadge level={item.access_level} groups={item.groups} />
              </td>
              <td data-testid="data-handling" className="data-handling-any">
                {item.local_only ? (
                  <span className="local-badge">{t("admin.knowledge.dataHandling.local")}</span>
                ) : (
                  t("admin.knowledge.dataHandling.any")
                )}
              </td>
              <td data-testid="document-count">{item.documents.total}</td>
              <td data-testid="collection-status">
                <StatusText item={item} />
              </td>
              <td data-testid="used-by">
                {item.used_by.length > 0
                  ? item.used_by.map((assistant) => assistant.name).join(", ")
                  : t("admin.knowledge.usedBy.none")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
