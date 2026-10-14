// EA-16 AC3: CSV helpers (RFC 4180) used for scripts.csv and the cross-labelling sheets.
// Run: node --test "eval/datasets/mekong-devworks/checks/csv.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import { formatCsv, parseCsv } from "../tools/csv.mjs";

const HEADER = ["id", "text", "note"];

test("csv_round_trip_keeps_comma_quote_newline_and_vietnamese", () => {
  const rows = [
    { id: "a", text: 'say "hi", please', note: "line1\nline2" },
    { id: "b", text: "Hủy đơn nghỉ phép", note: "" },
  ];
  const csv = formatCsv(rows, HEADER);
  const parsed = parseCsv(csv);
  assert.deepEqual(parsed.header, HEADER);
  assert.deepEqual(parsed.rows, rows);
});

test("format_csv_quotes_only_fields_that_need_it_and_uses_lf", () => {
  const csv = formatCsv([{ id: "a", text: "plain", note: "x,y" }], HEADER);
  assert.equal(csv, 'id,text,note\na,plain,"x,y"\n');
  assert.ok(!csv.includes("\r"));
});

test("parse_csv_reads_crlf_and_lf_identically", () => {
  const lf = 'id,text,note\na,"b,c",d\ne,f,g\n';
  const crlf = lf.replace(/\n/g, "\r\n");
  assert.deepEqual(parseCsv(crlf), parseCsv(lf));
});

test("parse_csv_strips_a_leading_utf8_bom", () => {
  const parsed = parseCsv("﻿id,text,note\na,b,c\n");
  assert.deepEqual(parsed.header, HEADER);
  assert.deepEqual(parsed.rows, [{ id: "a", text: "b", note: "c" }]);
});

test("parse_csv_keeps_escaped_quotes_and_empty_fields", () => {
  const parsed = parseCsv('id,text,note\na,"he said ""no""",\n');
  assert.deepEqual(parsed.rows, [{ id: "a", text: 'he said "no"', note: "" }]);
});
