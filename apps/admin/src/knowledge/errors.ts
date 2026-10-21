const FORBIDDEN = 403;
const CONFLICT = 409;
const UNPROCESSABLE = 422;

/** The i18n key of the message for an API error (contract "UI error messages"). */
export function knowledgeErrorKey(
  status: number,
  code: string,
  subject: "collection" | "folder",
): string {
  if (status === FORBIDDEN) return "admin.knowledge.error.forbidden";
  if (status === CONFLICT && code === "name_taken") {
    return `admin.knowledge.error.nameTaken.${subject}`;
  }
  if (status === CONFLICT && code === "folder_not_empty") {
    return "admin.knowledge.error.folderNotEmpty";
  }
  if (status === UNPROCESSABLE && code === "folder_too_deep") {
    return "admin.knowledge.error.folderTooDeep";
  }
  if (status === UNPROCESSABLE && code === "groups_required") {
    return "admin.knowledge.error.groupsRequired";
  }
  if (status === UNPROCESSABLE && code === "invalid_group") {
    return "admin.knowledge.error.invalidGroup";
  }
  return "admin.knowledge.error.generic";
}
