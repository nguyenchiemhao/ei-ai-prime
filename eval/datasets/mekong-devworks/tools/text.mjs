// Text helpers: normalisation for the test/example separation rule (AC4) and small extractors.

export function normalise(s) {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function hasVietnameseDiacritics(s) {
  return /\p{M}/u.test(s.normalize("NFD")) || /[đĐ]/.test(s);
}

export function extractUrls(s) {
  return (s.match(/https?:\/\/[^\s<>"')\]]+/g) || []).map((u) => u.replace(/[.,;:!?]+$/, ""));
}

export function extractVariables(s) {
  return [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
}
