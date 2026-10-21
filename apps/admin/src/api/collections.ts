import type { components } from "@ei-ai/api-types";
import { type ApiResult, apiRequest } from "./client";

export type CollectionItem = components["schemas"]["CollectionItem"];
export type CollectionDetail = components["schemas"]["CollectionDetail"];
export type FolderItem = components["schemas"]["FolderItem"];
export type CollectionCreate = components["schemas"]["CollectionCreate"];
export type CollectionUpdate = components["schemas"]["CollectionUpdate"];
export type AccessChange = components["schemas"]["AccessChange"];

const base = (workspaceId: string) => `/workspaces/${encodeURIComponent(workspaceId)}/collections`;
const one = (workspaceId: string, id: string) => `${base(workspaceId)}/${encodeURIComponent(id)}`;
const folder = (workspaceId: string, id: string, folderId: string) =>
  `${one(workspaceId, id)}/folders/${encodeURIComponent(folderId)}`;

// Lists the collections of a Workspace, ordered by name.
export async function listCollections(workspaceId: string): Promise<ApiResult<CollectionItem[]>> {
  const result = await apiRequest<{ collections: CollectionItem[] }>("GET", base(workspaceId));
  return result.ok ? { ok: true, data: result.data.collections } : result;
}

export function getCollection(
  workspaceId: string,
  id: string,
): Promise<ApiResult<CollectionDetail>> {
  return apiRequest<CollectionDetail>("GET", one(workspaceId, id));
}

export function createCollection(
  workspaceId: string,
  body: CollectionCreate,
): Promise<ApiResult<CollectionItem>> {
  return apiRequest<CollectionItem>("POST", base(workspaceId), body);
}

export function updateCollection(
  workspaceId: string,
  id: string,
  body: CollectionUpdate,
): Promise<ApiResult<CollectionItem>> {
  return apiRequest<CollectionItem>("PATCH", one(workspaceId, id), body);
}

export function changeCollectionAccess(
  workspaceId: string,
  id: string,
  body: AccessChange,
): Promise<ApiResult<CollectionItem>> {
  return apiRequest<CollectionItem>("PUT", `${one(workspaceId, id)}/access`, body);
}

export function deleteCollection(workspaceId: string, id: string): Promise<ApiResult<void>> {
  return apiRequest<void>("DELETE", one(workspaceId, id));
}

export function createFolder(
  workspaceId: string,
  id: string,
  body: { name: string; parent_id?: string | null },
): Promise<ApiResult<FolderItem>> {
  return apiRequest<FolderItem>("POST", `${one(workspaceId, id)}/folders`, body);
}

export function renameFolder(
  workspaceId: string,
  id: string,
  folderId: string,
  body: { name: string },
): Promise<ApiResult<FolderItem>> {
  return apiRequest<FolderItem>("PATCH", folder(workspaceId, id, folderId), body);
}

export function deleteFolder(
  workspaceId: string,
  id: string,
  folderId: string,
): Promise<ApiResult<void>> {
  return apiRequest<void>("DELETE", folder(workspaceId, id, folderId));
}
