import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest, apiUpload } from "./client";

export type DocumentItem = components["schemas"]["DocumentItem"];
export type DocumentText = { text: string; truncated: boolean; total_characters: number };

const base = (workspaceId: string, collectionId: string) =>
  `/workspaces/${encodeURIComponent(workspaceId)}/collections/${encodeURIComponent(collectionId)}`;
const one = (workspaceId: string, collectionId: string, id: string) =>
  `${base(workspaceId, collectionId)}/documents/${encodeURIComponent(id)}`;

// Lists the documents of a collection, or of one folder, newest first.
// Input: workspaceId, collectionId, folderId (optional). Output: ApiResult<DocumentItem[]>
export const listDocuments = async (
  workspaceId: string,
  collectionId: string,
  folderId?: string | null,
): Promise<ApiResult<DocumentItem[]>> => {
  const query = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : "";
  const result = await apiRequest<{ documents: DocumentItem[] }>(
    "GET",
    `${base(workspaceId, collectionId)}/documents${query}`,
  );
  return result.ok ? { ok: true, data: result.data.documents } : result;
};

// Uploads one file into a folder as a raw body; the name travels percent-encoded in X-File-Name.
// Input: workspaceId, collectionId, folderId, file (File). Output: ApiResult<DocumentItem>
export const uploadDocument = (
  workspaceId: string,
  collectionId: string,
  folderId: string,
  file: File,
): Promise<ApiResult<DocumentItem>> =>
  apiUpload<DocumentItem>(
    `${base(workspaceId, collectionId)}/folders/${encodeURIComponent(folderId)}/documents`,
    file,
    {
      "Content-Type": "application/octet-stream",
      "X-File-Name": encodeURIComponent(file.name),
    },
  );

// Gets the extracted text of a ready document (first 100 000 characters).
export const getDocumentText = (
  workspaceId: string,
  collectionId: string,
  id: string,
): Promise<ApiResult<DocumentText>> =>
  apiRequest<DocumentText>("GET", `${one(workspaceId, collectionId, id)}/text`);

// Deletes a document with its chunks and stored original.
export const deleteDocument = (
  workspaceId: string,
  collectionId: string,
  id: string,
): Promise<ApiResult<void>> => apiRequest<void>("DELETE", one(workspaceId, collectionId, id));
