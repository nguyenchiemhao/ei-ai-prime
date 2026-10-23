import { useTranslation } from "react-i18next";
import type { DocumentItem } from "../api/documents";

const FALLBACK_REASON = "processing_error";
const BASE = "admin.knowledge.documents";

/** Status cell of a document: the status badge and, for failed or unsupported files, the reason. */
export function DocumentStatus({ document }: { document: DocumentItem }) {
  const { t } = useTranslation();
  const { status, progress, page_count: pages, reason } = document;
  let label: string;

  if (status === "processing") label = t(`${BASE}.status.processing`, { percent: progress ?? 0 });
  else if (status === "ready") {
    label =
      pages === 1 ? t(`${BASE}.status.readyOne`) : t(`${BASE}.status.ready`, { count: pages ?? 0 });
  } else if (status === "not_supported") label = t(`${BASE}.status.notSupported`);
  else label = t(`${BASE}.status.${status}`);

  const showReason = status === "failed" || status === "not_supported";

  return (
    <>
      <span className="document-status" data-testid="document-status" data-status={status}>
        {label}
      </span>
      {status === "processing" ? (
        <div className="document-progress" data-testid="document-progress" aria-hidden="true">
          <div style={{ width: `${Math.min(100, Math.max(0, progress ?? 0))}%` }} />
        </div>
      ) : null}
      {showReason ? (
        <p className="document-reason" data-testid="document-reason">
          {t(`${BASE}.reason.${reason ?? FALLBACK_REASON}`, {
            defaultValue: t(`${BASE}.reason.${FALLBACK_REASON}`),
          })}
        </p>
      ) : null}
    </>
  );
}
