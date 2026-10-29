// English first, Swahili-ready (docs/spec/04 principle 6). No locale in the URL.
//
// Swahili is a draft until the native-speaker review at gate G5 (docs/platform/design/phase1-auth-ui.md, GATES.md),
// so every request is served in English for now. locales/sw.json stays in the repo with identical keys (checked by
// locales/locales.test.ts); set SWAHILI_LIVE to true at G5 to let the NEXT_LOCALE cookie, then the browser's
// Accept-Language, choose it.

export const locales = ["en", "sw"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";
export const SWAHILI_LIVE = false;

function pick(value: string | undefined | null): Locale | undefined {
  const tag = value?.toLowerCase().slice(0, 2);
  return locales.find((l) => l === tag);
}

/** The locale for a request: English until G5, then the cookie, the Accept-Language header, or English. */
export function resolveLocale(
  cookieValue: string | undefined | null,
  acceptLanguage: string | undefined | null,
  swahiliLive: boolean = SWAHILI_LIVE,
): Locale {
  if (!swahiliLive) return defaultLocale;
  return pick(cookieValue) ?? pick(acceptLanguage) ?? defaultLocale;
}
