import { describe, expect, it } from "vitest";
import { MAX_FILE_BYTES, checkFile, formatSize } from "./uploadRules";

const fileOf = (name: string, size = 10): File => {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
};

describe("checkFile", () => {
  it("rejects_unsupported_extensions", () => {
    expect(checkFile(fileOf("setup.exe"))).toBe("unsupported_format");
    expect(checkFile(fileOf("old.doc"))).toBe("unsupported_format");
    expect(checkFile(fileOf("table.XLSX"))).toBe("unsupported_format");
    expect(checkFile(fileOf("noextension"))).toBe("unsupported_format");
  });

  it("accepts_supported_extensions_case_insensitively", () => {
    expect(checkFile(fileOf("a.PDF"))).toBeNull();
    expect(checkFile(fileOf("a.docx"))).toBeNull();
    expect(checkFile(fileOf("a.Md"))).toBeNull();
    expect(checkFile(fileOf("a.b.txt"))).toBeNull();
  });

  it("rejects_only_files_over_the_limit", () => {
    expect(MAX_FILE_BYTES).toBe(52_428_800);
    expect(checkFile(fileOf("a.pdf", 52_428_800))).toBeNull();
    expect(checkFile(fileOf("a.pdf", 52_428_801))).toBe("file_too_large");
  });
});

describe("formatSize", () => {
  it("formats_bytes_kilobytes_and_megabytes", () => {
    expect(formatSize(0, "en")).toBe("0 B");
    expect(formatSize(1023, "en")).toBe("1023 B");
    expect(formatSize(14336, "en")).toBe("14 KB");
    expect(formatSize(1258291, "en")).toBe("1.2 MB");
  });

  it("uses_the_locale_decimal_separator", () => {
    expect(formatSize(1258291, "vi")).toBe("1,2 MB");
  });
});
