import { looksLikePhone } from "./phone.js";

const PUBLIC_ID = /^[a-z0-9._-]{4,20}$/i;
const EXPLICIT_PUBLIC_ID = /^(?:id\s*:\s*|#|@)([a-z0-9._-]{4,20})$/i;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Resolve an input without treating ordinary public IDs as phone numbers. */
export function contactLookupType(value) {
  const term = String(value ?? "").trim();
  if (!term) return null;
  if (EXPLICIT_PUBLIC_ID.test(term)) return "public_id";
  if (EMAIL.test(term)) return "email";
  if (looksLikePhone(term)) return "phone";
  if (PUBLIC_ID.test(term) && /[a-z._-]/i.test(term)) return "public_id";
  // All-numeric IDs are ambiguous with phone numbers; @id: or # makes them explicit.
  return null;
}

export function normalizePublicIdQuery(value) {
  const term = String(value ?? "").trim();
  const explicit = term.match(EXPLICIT_PUBLIC_ID);
  const candidate = explicit ? explicit[1] : term;
  return PUBLIC_ID.test(candidate) ? candidate.toLowerCase() : "";
}
