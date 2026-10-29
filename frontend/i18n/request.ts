import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { resolveLocale } from "./locale";

export { defaultLocale, locales, type Locale } from "./locale";

export default getRequestConfig(async () => {
  const locale = resolveLocale((await cookies()).get("NEXT_LOCALE")?.value, (await headers()).get("accept-language"));
  return {
    locale,
    messages: (await import(`../locales/${locale}.json`)).default,
  };
});
