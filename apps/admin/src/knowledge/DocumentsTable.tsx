import { useTranslation } from "react-i18next";
import type { DocumentItem } from "../api/documents";
import { lastActive } from "../members/lastActive";
import { DocumentStatus } from "./DocumentStatus";
import { formatSize } from "./uploadRules";

interface Props {
  documents: readonly DocumentItem[];
  /** Language of the UI, for the size and date formats. */
  locale: string;
  /** Whether a folder is selected (the empty message differs from "All documents"). */
  inFolder: boolean;
  onPreview(document: DocumentItem): void;
  onRemove(document: DocumentItem): void;
}

const SEPARATOR = " · ";
const BASE = "admin.knowledge.documents";

// Formats a timestamp as "DD Mon" in the UI language.
// Input: iso (string), locale (string). Output: string
const formatDay = (iso: string, locale: string): string => {
  const parts = new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short" }).formatToParts(
    new Date(iso),
  );
  const day = parts.find((part) => part.type === "day")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  return `${day} ${month}`;
};

/** The documents of the selected folder (or the whole collection): name, status, size, updated. */
export function DocumentsTable({ documents, locale, inFolder, onPreview, onRemove }: Props) {
  const { t } = useTranslation();

  // Builds "Today · Thao Nguyen", "Yesterday · ..." or "02 Oct · ..." (date only without uploader).
  const updatedText = (document: DocumentItem): string => {
    const when = lastActive(document.updated_at, new Date());
    let day: string;
    if (when.key === "today") day = t("admin.members.lastActive.today");
    else if (when.key === "yesterday") day = t("admin.members.lastActive.yesterday");
    else day = formatDay(document.updated_at, locale);
    return document.uploaded_by ? `${day}${SEPARATOR}${document.uploaded_by.display_name}` : day;
  };

  if (documents.length === 0) {
    return (
      <p className="folders-empty" data-testid="documents-empty">
        {inFolder ? t(`${BASE}.folderEmpty`) : t("admin.knowledge.detail.documentsEmpty")}
      </p>
    );
  }

  return (
    <div className="members-scroll">
      <table
        className="members-table documents-table"
        data-testid="documents-table"
        aria-label={t(`${BASE}.table.label`)}
      >
        <thead>
          <tr>
            <th scope="col">{t(`${BASE}.table.document`)}</th>
            <th scope="col">{t(`${BASE}.table.status`)}</th>
            <th scope="col">{t(`${BASE}.table.size`)}</th>
            <th scope="col">{t(`${BASE}.table.updated`)}</th>
            <th scope="col">{t(`${BASE}.table.actions`)}</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => (
            <tr
              key={document.id}
              className="document-row"
              data-testid="document-row"
              data-document-id={document.id}
              data-status={document.status}
            >
              <td data-testid="document-name">{document.name}</td>
              <td>
                <DocumentStatus document={document} />
              </td>
              <td className="document-nowrap" data-testid="document-size">
                {formatSize(document.size_bytes, locale)}
              </td>
              <td className="document-nowrap" data-testid="document-updated">
                {updatedText(document)}
              </td>
              <td className="document-nowrap">
                {document.status === "ready" ? (
                  <button
                    type="button"
                    className="button-link"
                    data-testid="preview-text"
                    aria-label={t(`${BASE}.previewLabel`, { name: document.name })}
                    onClick={() => onPreview(document)}
                  >
                    {t(`${BASE}.previewText`)}
                  </button>
                ) : null}
                {document.status === "failed" || document.status === "not_supported" ? (
                  <button
                    type="button"
                    className="button-link"
                    data-testid="remove-document"
                    aria-label={t(`${BASE}.removeLabel`, { name: document.name })}
                    onClick={() => onRemove(document)}
                  >
                    {t(`${BASE}.remove`)}
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
