// EA-13 (SET-03) coding rule 7: the VI and EN catalogs cover the same keys, have no empty or
// untranslated values and are valid UTF-8 in NFC (D60).
// Run:  node --test packages/i18n/test/catalog.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MESSAGES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../messages");
// Values that are legitimately identical in both languages: the product name and language names.
const SAME_IN_BOTH = new Set(["common.productName", "common.language.en", "common.language.vi"]);
const NAMESPACES = ["admin", "widget", "common"];

const read = (name) => fs.readFileSync(path.join(MESSAGES, name));
const parse = (name) => JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(read(name)));

function flatten(node, prefix = "") {
  return Object.entries(node).flatMap(([key, value]) =>
    typeof value === "object" && value !== null
      ? flatten(value, `${prefix}${key}.`)
      : [[`${prefix}${key}`, value]],
  );
}

const en = new Map(flatten(parse("en.json")));
const vi = new Map(flatten(parse("vi.json")));

test("vi_and_en_have_the_same_keys", () => {
  assert.deepEqual([...vi.keys()].sort(), [...en.keys()].sort());
  assert.ok(en.size > 0);
});

test("only_the_agreed_namespaces_are_used", () => {
  for (const key of en.keys())
    assert.ok(NAMESPACES.includes(key.split(".")[0]), `${key}: unknown namespace`);
});

test("no_empty_or_untranslated_values", () => {
  for (const [key, value] of en) {
    assert.ok(typeof value === "string" && value.trim() !== "", `en ${key} is empty`);
    const translated = vi.get(key);
    assert.ok(typeof translated === "string" && translated.trim() !== "", `vi ${key} is empty`);
    if (!SAME_IN_BOTH.has(key))
      assert.notEqual(translated, value, `vi ${key} is identical to en (untranslated)`);
  }
});

test("files_are_valid_utf8_nfc", () => {
  for (const name of ["en.json", "vi.json"]) {
    const bytes = read(name);
    assert.notDeepEqual([...bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf], `${name} has a BOM`);
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    assert.equal(text, text.normalize("NFC"), `${name} is not NFC`);
    assert.ok(!text.includes("\r"), `${name} must use LF`);
  }
  assert.ok(
    [...vi.values()].some((v) =>
      /[ạảãàáâấầẩẫậắằẳẵặẹẻẽèéêếềểễệịỉĩìíọỏõòóôốồổỗộớờởỡợụủũùúưứừửữựỳỵỷỹýđ]/i.test(v),
    ),
    "vi catalog has no Vietnamese diacritics",
  );
});
