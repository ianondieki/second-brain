// The prior-knowledge declaration's fingerprint (REQ-PROV-06; docs/spec/06 6.4 pt 5): the SHA-256 of the
// organisation's evidence, computed in the browser with Web Crypto. Only the 64 hex digits leave the device; the file
// is read into memory here and never sent anywhere.

/** Files up to this size are hashed in the browser (read whole with `arrayBuffer()`); above it, paste the hash. */
export const HASH_MAX_BYTES = 50 * 1024 * 1024;

/** A SHA-256 as 64 lowercase hex digits, or null when `text` is not one (spaces around it and upper case allowed). */
export function asSha256(text: string): string | null {
  const value = text.trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(value) ? value : null;
}

/** The SHA-256 of a file's bytes, as 64 lowercase hex digits (what `sha256sum` prints). */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The Nairobi calendar day of an instant ("2026-10-02"), for a date input's limit. */
export function nairobiDay(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date(iso));
}
