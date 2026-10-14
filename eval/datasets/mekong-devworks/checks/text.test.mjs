// EA-16 AC4: text normalisation used to separate test questions from script examples.
// Run: node --test "eval/datasets/mekong-devworks/checks/text.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import { normalise, hasVietnameseDiacritics, extractUrls, extractVariables } from "../tools/text.mjs";

test("normalise_strips_diacritics_case_punctuation_and_spaces", () => {
  assert.equal(normalise("Hủy đơn nghỉ phép?"), "huy don nghi phep");
  assert.equal(normalise("ĐƠN  xin   nghỉ!!"), "don xin nghi");
  assert.equal(normalise("  How do I cancel my leave?  "), "how do i cancel my leave");
  assert.equal(normalise("OT, ngày lễ... tính ntn?"), "ot ngay le tinh ntn");
});

test("normalise_treats_nfd_and_nfc_alike", () => {
  const nfc = "Hủy đơn nghỉ phép".normalize("NFC");
  const nfd = "Hủy đơn nghỉ phép".normalize("NFD");
  assert.notEqual(nfc, nfd);
  assert.equal(normalise(nfc), normalise(nfd));
});

test("normalise_makes_an_unaccented_copy_equal_to_the_accented_text", () => {
  assert.equal(normalise("huy phep da duyet"), normalise("Hủy phép đã duyệt"));
});

test("has_vietnamese_diacritics_detects_accents_and_d_stroke", () => {
  assert.equal(hasVietnameseDiacritics("cach xin nghi phep"), false);
  assert.equal(hasVietnameseDiacritics("cách xin nghi phep"), true);
  assert.equal(hasVietnameseDiacritics("di lam"), false);
  assert.equal(hasVietnameseDiacritics("đi lam"), true);
  assert.equal(hasVietnameseDiacritics("Đi lam"), true);
  assert.equal(hasVietnameseDiacritics("Hủy".normalize("NFD")), true);
});

test("extract_urls_finds_http_and_https_urls_without_trailing_punctuation", () => {
  assert.deepEqual(extractUrls("See https://portal.mekongdevworks.example/vpn, then http://a.example."), [
    "https://portal.mekongdevworks.example/vpn",
    "http://a.example",
  ]);
  assert.deepEqual(extractUrls("no url"), []);
});

test("extract_variables_finds_curly_brace_tokens", () => {
  assert.deepEqual(extractVariables("Chào {name}, mở {page} nhé {name}"), ["name", "page", "name"]);
  assert.deepEqual(extractVariables("nothing"), []);
});
