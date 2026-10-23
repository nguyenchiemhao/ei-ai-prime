import { useCallback, useEffect, useRef, useState } from "react";
import { type DocumentItem, listDocuments } from "../api/documents";

export const POLL_INTERVAL_MS = 2000;
const ACTIVE_STATUSES = ["queued", "processing"];

export interface DocumentsError {
  status: number;
  code: string;
}

// A network error or a server error (502 while the API restarts) is worth another try.
const isTransient = (status: number) => status === 0 || status >= 500;

// Loads the documents of a collection (all, or one folder) and keeps them fresh while any is
// still queued or processing. A failed poll keeps the last rows and polls again while rows are
// active or the failure is transient; the next success clears the error.
// Input: workspaceId, collectionId, folderId (null = every folder), onRecovered (called when a
// list loads after a failed one: counts shown elsewhere may be stale)
// Output: { documents, loading (first list not loaded yet), reload, error }
export const useDocuments = (
  workspaceId: string,
  collectionId: string,
  folderId: string | null,
  onRecovered?: () => void,
) => {
  const key = `${workspaceId}/${collectionId}/${folderId ?? ""}`;
  const [loaded, setLoaded] = useState<{ key: string; items: DocumentItem[] } | null>(null);
  const [failure, setFailure] = useState<{ key: string; error: DocumentsError } | null>(null);
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((current) => current + 1), []);
  const recoveredRef = useRef(onRecovered);
  useEffect(() => {
    recoveredRef.current = onRecovered;
  }, [onRecovered]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = false;
    let failed = false;
    const schedule = () => {
      timer = setTimeout(() => void load(), POLL_INTERVAL_MS);
    };

    const load = async () => {
      const result = await listDocuments(workspaceId, collectionId, folderId);
      if (cancelled) return;
      if (!result.ok) {
        setFailure({ key, error: { status: result.status, code: result.code } });
        failed = true;
        if (active || isTransient(result.status)) schedule();
        return;
      }
      setFailure(null);
      if (failed) {
        failed = false;
        recoveredRef.current?.();
      }
      setLoaded({ key, items: result.data });
      active = result.data.some((item) => ACTIVE_STATUSES.includes(item.status));
      if (active) schedule();
    };

    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [workspaceId, collectionId, folderId, key, version]);

  // Documents of another folder are never shown while the new list loads.
  const error = failure?.key === key ? failure.error : null;
  const current = loaded?.key === key ? loaded : null;
  return {
    documents: current?.items ?? [],
    loading: current === null && error === null,
    reload,
    error,
  };
};
