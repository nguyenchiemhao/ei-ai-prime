// Minimal RFC 4180 CSV writer/reader (UTF-8, LF on write, CRLF or LF on read, BOM tolerated).

function quote(field) {
  const s = String(field ?? "");
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function formatCsv(rows, header) {
  const lines = [header.map(quote).join(",")];
  for (const row of rows) lines.push(header.map((h) => quote(row[h])).join(","));
  return lines.join("\n") + "\n";
}

function parseRecords(text) {
  const records = [];
  let record = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") {
      record.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      record.push(field);
      records.push(record);
      record = [];
      field = "";
    } else field += c;
  }
  if (field !== "" || record.length > 0) {
    record.push(field);
    records.push(record);
  }
  return records;
}

export function parseCsv(text) {
  const records = parseRecords(text.replace(/^﻿/, ""));
  const header = records.shift() ?? [];
  const rows = records.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
  return { header, rows };
}
