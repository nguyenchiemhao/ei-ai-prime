export const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".md", ".txt"];
export const MAX_FILE_BYTES = 52_428_800;

const BYTES_PER_KB = 1024;
const BYTES_PER_MB = 1_048_576;

export type FileRejection = "unsupported_format" | "file_too_large";

// Checks a chosen file against the supported formats and the size limit before any request.
// Input: file (File). Output: the rejection code, or null when the file may be uploaded.
export const checkFile = (file: File): FileRejection | null => {
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";

  if (!SUPPORTED_EXTENSIONS.includes(extension)) return "unsupported_format";
  if (file.size > MAX_FILE_BYTES) return "file_too_large";
  return null;
};

// Formats a byte count as "N B", "N KB" (rounded) or "N.N MB".
// Input: bytes (number), locale (string). Output: string
export const formatSize = (bytes: number, locale: string): string => {
  const megabytes = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

  if (bytes < BYTES_PER_KB) return `${bytes} B`;
  if (bytes < BYTES_PER_MB) return `${Math.round(bytes / BYTES_PER_KB)} KB`;
  return `${megabytes.format(bytes / BYTES_PER_MB)} MB`;
};
