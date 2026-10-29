import type messages from "./locales/en.json";
import type { Locale } from "./i18n/request";

// Type-checked message keys: a typo in t("...") fails `tsc`. English is the source of the key set; the locale test
// keeps sw.json's keys identical.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof messages;
  }
}
