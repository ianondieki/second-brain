import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

// English first, Swahili-ready (docs/spec/04 principle 6). No locale in the URL: the NEXT_LOCALE cookie wins,
// then the browser's Accept-Language, then English.
export const locales = ["en", "sw"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

function pick(value: string | undefined | null): Locale | undefined {
  const tag = value?.toLowerCase().slice(0, 2);
  return locales.find((l) => l === tag);
}

export default getRequestConfig(async () => {
  const cookieLocale = pick((await cookies()).get("NEXT_LOCALE")?.value);
  const headerLocale = pick((await headers()).get("accept-language"));
  const locale = cookieLocale ?? headerLocale ?? defaultLocale;
  return {
    locale,
    messages: (await import(`../locales/${locale}.json`)).default,
  };
});
