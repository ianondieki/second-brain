import type { components, paths } from "@/lib/api/schema";

export type CertificateCheck = components["schemas"]["CertificateCheck"];
export type UploadCheck = components["schemas"]["UploadCheck"];

/** The API's certificate id pattern (GET /api/verify/{cert_id}, bridge/provenance/verify.py CERT_ID_REGEX). */
export const CERT_ID = /^[0-9A-Za-z]{8,24}$/;

/** POST /api/verify takes the raw file as its body (no multipart); files up to 10 MB (verify.MAX_UPLOAD_BYTES). */
export const UPLOAD_PATH = "/api/verify" satisfies keyof paths;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/**
 * A certificate id as someone typed or pasted it, ready to look up: spaces and hyphens (a printed id may be grouped)
 * are dropped, and letters are upper-cased, since ids use an upper-case alphabet (service.new_cert_id). Returns null
 * when what is left cannot be an id, so no request is made for it.
 */
export function normaliseCertId(raw: string | undefined | null): string | null {
  const compact = (raw ?? "").replace(/[\s\-‐-―]+/g, "").toUpperCase();
  return CERT_ID.test(compact) ? compact : null;
}

/** "3f9a…" (64 hex digits) as eight groups of eight, for reading aloud or comparing by eye. */
export function fingerprintGroups(hex: string): string[] {
  const groups: string[] = [];
  for (let i = 0; i < hex.length; i += 8) groups.push(hex.slice(i, i + 8));
  return groups;
}

/** The public token download for a certificate (proxied to the API like every /api path). */
export function tokenHref(certId: string): string {
  return `/api/verify/${encodeURIComponent(certId)}/timestamp.tsr`;
}

/** The published Ed25519 keys (served by the API outside /api; next.config.ts routes the path). */
export const KEYS_HREF = "/.well-known/provenance-keys.json";

/** An API time (ISO 8601, UTC) shown in Nairobi time and in UTC (docs/spec/07 item 7: store UTC, show EAT). */
export const NAIROBI = "Africa/Nairobi";

/**
 * A date and time as written in Kenya for the page's language ("29 September 2026 at 14:06:25"), not the US order
 * that plain "en" gives. The region is appended here; the language stays the app's.
 */
export function formatKenyan(locale: string, date: Date, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, options).format(date);
}
