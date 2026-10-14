// EA-16 AC6: only fake personal data in valid Vietnamese formats.
// Run: node --test "eval/datasets/mekong-devworks/checks/personal-data.test.mjs"
import test from "node:test";
import assert from "node:assert/strict";
import {
  isVietnamesePhone,
  isCccd,
  isCmnd,
  isReservedEmail,
  isReservedUrl,
  digitsOf,
  extractPersonalData,
  checkPersonalData,
  maskValue,
} from "../tools/personal-data.mjs";

test("accepts_vietnamese_mobile_and_landline_formats", () => {
  for (const ok of ["0912 345 678", "+84 912.345.678", "028 3823 4567", "0912345678", "+84912345678", "097.123.4567"]) {
    assert.equal(isVietnamesePhone(ok), true, ok);
  }
});

test("rejects_invalid_phone_prefix_or_length", () => {
  for (const bad of ["0123 456 789", "091234567", "09123456789", "+84 112 345 678", "1912345678", "028 3823 456"]) {
    assert.equal(isVietnamesePhone(bad), false, bad);
  }
});

test("accepts_cccd_with_known_province_and_century_digit", () => {
  assert.equal(isCccd("079203001234"), true);
  assert.equal(isCccd("001095004321"), true);
  assert.equal(isCmnd("025123456"), true);
});

test("rejects_cccd_with_unknown_province", () => {
  assert.equal(isCccd("099203001234"), false);
  assert.equal(isCccd("079703001234"), false);
  assert.equal(isCccd("07920300123"), false);
  assert.equal(isCmnd("02512345"), false);
});

test("accepts_only_reserved_email_domains", () => {
  assert.equal(isReservedEmail("an.do@mekongdevworks.example"), true);
  assert.equal(isReservedEmail("a@example.com"), true);
  assert.equal(isReservedEmail("a@example.org"), true);
  assert.equal(isReservedEmail("a@example.net"), true);
  assert.equal(isReservedEmail("an.do@gmail.com"), false);
  assert.equal(isReservedEmail("a@notexample.com"), false);
  assert.equal(isReservedEmail("not-an-email"), false);
  assert.equal(isReservedUrl("https://portal.mekongdevworks.example/vpn"), true);
  assert.equal(isReservedUrl("https://www.google.com"), false);
});

test("extracts_phone_and_id_candidates_but_not_amounts_or_dates", () => {
  const text =
    "Mình là An Do (emp-0042), SĐT 0912 345 678, CCCD 079203001234, mail an.do@mekongdevworks.example. " +
    "Lương 15.000.000 đ, ngày 24/10/2026, máy lẻ ext. 1234, năm 2027.";
  const found = extractPersonalData(text);
  assert.deepEqual(found.emails, ["an.do@mekongdevworks.example"]);
  assert.deepEqual(found.numbers, ["0912 345 678", "079203001234"]);
  assert.deepEqual(found.employeeCodes, ["emp-0042"]);
});

test("check_personal_data_requires_registry_entries_for_numbers", () => {
  const registry = { phones: ["0912 345 678"], emails: [], national_ids: ["079203001234"], names: [] };
  assert.deepEqual(checkPersonalData("SĐT +84 912.345.678 và CCCD 079 203 001 234", registry), []);
  assert.equal(digitsOf("+84 912.345.678"), "0912345678");
  assert.match(checkPersonalData("gọi 0987 654 321", registry)[0], /not registered/);
  assert.match(checkPersonalData("gọi 0123 456 789", registry)[0], /neither/);
  assert.match(checkPersonalData("mail a@gmail.com", registry)[0], /reserved/);
});

test("extracts_numbers_written_with_hyphens_and_brackets", () => {
  assert.deepEqual(extractPersonalData("Gọi 0912-345-678 hoặc (028) 3822 1099 nhé").numbers, ["0912-345-678", "(028) 3822 1099"]);
  assert.equal(isVietnamesePhone("0912-345-678"), true);
  assert.equal(isVietnamesePhone("(028) 3822 1099"), true);
  assert.equal(digitsOf("(028) 3822-1099"), "02838221099");
  const registry = { phones: [], emails: [], national_ids: [], names: [] };
  assert.match(checkPersonalData("gọi 0912-345-678", registry)[0], /not registered/);
});

test("does_not_treat_money_amounts_or_iso_dates_as_personal_numbers", () => {
  const text = "Thưởng 100.000.000 đồng, phí 120.000.000đ, lương VND 150.000.000, ngày 2027-01-15 và 15-01-2027.";
  assert.deepEqual(extractPersonalData(text).numbers, []);
  assert.deepEqual(checkPersonalData(text, { phones: [], emails: [], national_ids: [], names: [] }), []);
});

test("masks_numbers_and_email_local_parts_in_error_messages", () => {
  const registry = { phones: [], emails: [], national_ids: [], names: [] };
  const [phone] = checkPersonalData("gọi 0987 654 321", registry);
  assert.ok(!phone.includes("0987 654 321") && !phone.includes("987 654"), phone);
  assert.match(phone, /09\*\* \*\*\* 321/);
  const [mail] = checkPersonalData("mail an.do@gmail.com", registry);
  assert.ok(!mail.includes("an.do"), mail);
  assert.match(mail, /a\*\*\*@gmail\.com/);
  assert.equal(maskValue("079203001234"), "07*******234");
  assert.equal(maskValue("(028) 3822 1099"), "(02*) **** *099");
});
