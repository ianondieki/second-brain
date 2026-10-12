// The data-saver switch (P27 track F; REQ-UX-08; docs/spec/07 item 5): a cookie the server treats exactly like the
// browser's `Save-Data: on` hint, so a person on a thin connection gets no photographs (the lattice bands instead) and
// the smallest images. Settings › Profile sets it on this device; nothing about it is stored on the account. Not
// HttpOnly, so the switch can read it; it carries no personal data.

export const DATA_SAVER_COOKIE = "data-saver";
/** One year, in seconds. */
export const DATA_SAVER_MAX_AGE = 31_536_000;

const ON = new RegExp(`(?:^|;)\\s*${DATA_SAVER_COOKIE}=1\\s*(?:;|$)`);

/** Whether a Cookie header (or `document.cookie`) carries the switch turned on. */
export function dataSaverIn(cookie: string | null | undefined): boolean {
  return ON.test(cookie ?? "");
}

/**
 * Whether a request asks to save data: the `Save-Data: on` client hint, or the switch's cookie. `get` reads a request
 * header by name (case-insensitive, as Headers does).
 */
export function asksToSaveData(get: (name: string) => string | null | undefined): boolean {
  return get("save-data")?.trim().toLowerCase() === "on" || dataSaverIn(get("cookie"));
}

/**
 * The `document.cookie` assignment that turns the switch on (for a year) or off (expired now): the whole site, sent on
 * same-site navigations, Secure where the site is served over HTTPS.
 */
export function dataSaverCookie(on: boolean, secure: boolean): string {
  const value = on ? "1" : "";
  const age = on ? DATA_SAVER_MAX_AGE : 0;
  return `${DATA_SAVER_COOKIE}=${value}; Path=/; Max-Age=${age}; SameSite=Lax${secure ? "; Secure" : ""}`;
}
