import type { FolderItem } from "../api/collections";

// Orders a flat folder list as a tree: each folder is followed by its subfolders, siblings by name.
// Input: folders (FolderItem[]). Output: FolderItem[]
export const orderAsTree = (folders: readonly FolderItem[]): FolderItem[] => {
  const byParent = new Map<string | null, FolderItem[]>();
  const ordered: FolderItem[] = [];

  for (const item of folders) {
    const siblings = byParent.get(item.parent_id ?? null) ?? [];
    siblings.push(item);
    byParent.set(item.parent_id ?? null, siblings);
  }
  const visit = (parentId: string | null) => {
    const siblings = byParent.get(parentId) ?? [];
    siblings.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    for (const item of siblings) {
      ordered.push(item);
      visit(item.id);
    }
  };
  visit(null);
  return ordered;
};
