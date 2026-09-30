import { useTranslations } from "next-intl";

import { DEV_SECTIONS, type DevSection } from "./nav-sections";
import { PortalNav } from "./PortalNav";

export { DEV_SECTIONS, type DevSection } from "./nav-sections";

/** The developer portal's navigation (PortalNav: bottom tabs under 1024 px, a left rail from 1024 px). */
export function DevNav({ current }: { current: DevSection }) {
  const t = useTranslations("nav");
  return (
    <PortalNav
      label={t("developer")}
      current={current}
      items={DEV_SECTIONS.map(({ key, href, Icon }) => ({ key, href, Icon, label: t(key) }))}
    />
  );
}
