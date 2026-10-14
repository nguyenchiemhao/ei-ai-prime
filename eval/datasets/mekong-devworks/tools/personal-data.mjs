// Rules for the fake personal data allowed in the test set (AC6, labeling_guide.md section 7).

const PROVINCES = ["001", "031", "048", "079", "092"];
const RESERVED_DOMAINS = ["example.com", "example.org", "example.net"];
const SEPARATORS = /[\s.\-()]/g;
const CURRENCY_AFTER = /^\s*(?:đồng|vnd|vnđ|đ)(?![\p{L}])/iu;
const CURRENCY_BEFORE = /(?:vnd|vnđ)\s*$/i;

function compact(raw) {
  return raw.replace(SEPARATORS, "");
}

export function digitsOf(raw) {
  const c = compact(raw);
  return c.startsWith("+84") ? "0" + c.slice(3).replace(/\D/g, "") : c.replace(/\D/g, "");
}

export function isVietnamesePhone(raw) {
  const c = compact(raw);
  return /^(?:0|\+84)[35789]\d{8}$/.test(c) || /^(?:0|\+84)2\d{9}$/.test(c);
}

export function isCccd(digits) {
  return /^\d{12}$/.test(digits) && PROVINCES.includes(digits.slice(0, 3)) && /[0-3]/.test(digits[3]);
}

export function isCmnd(digits) {
  return /^\d{9}$/.test(digits);
}

function isReservedHost(domain) {
  const d = domain.toLowerCase();
  return RESERVED_DOMAINS.includes(d) || d.endsWith(".example");
}

export function isReservedEmail(addr) {
  const m = /^[\w.+-]+@([\w-]+(?:\.[\w-]+)+)$/.exec(addr);
  return m !== null && isReservedHost(m[1]);
}

export function isReservedUrl(url) {
  try {
    return isReservedHost(new URL(url).hostname);
  } catch {
    return false;
  }
}

// Masked form for error messages: validator output may reach CI logs (CLAUDE.md rule 3).
export function maskValue(value) {
  const at = value.indexOf("@");
  if (at > 0) return `${value[0]}***${value.slice(at)}`;
  let seen = 0;
  const total = (value.match(/\d/g) || []).length;
  return value.replace(/\d/g, (d) => {
    seen++;
    return seen <= 2 || seen > total - 3 ? d : "*";
  });
}

export function extractPersonalData(text) {
  const emails = text.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) || [];
  const numbers = [];
  for (const m of text.matchAll(/\+?\(?\d[\d .\-()]*\d/g)) {
    const candidate = m[0].trim();
    if (candidate.replace(/\D/g, "").length < 9) continue;
    const after = text.slice(m.index + m[0].length);
    const before = text.slice(0, m.index);
    if (CURRENCY_AFTER.test(after) || CURRENCY_BEFORE.test(before)) continue;
    numbers.push(candidate);
  }
  const employeeCodes = text.match(/\bemp-\d{4}\b/g) || [];
  return { emails, numbers, employeeCodes };
}

export function checkPersonalData(text, registry) {
  const errors = [];
  const { emails, numbers } = extractPersonalData(text);
  const known = new Set([...(registry.phones || []), ...(registry.national_ids || [])].map(digitsOf));
  for (const email of emails) {
    if (!isReservedEmail(email)) errors.push(`email "${maskValue(email)}" is not on a reserved domain`);
  }
  for (const number of numbers) {
    const digits = digitsOf(number);
    if (!isVietnamesePhone(number) && !isCccd(digits) && !isCmnd(digits)) {
      errors.push(`number "${maskValue(number)}" is neither a valid Vietnamese phone nor a CCCD/CMND`);
    } else if (!known.has(digits)) {
      errors.push(`number "${maskValue(number)}" is not registered in fake_personal_data.json`);
    }
  }
  return errors;
}
