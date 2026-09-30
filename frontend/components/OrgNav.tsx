import { useTranslations } from "next-intl";

import { ORG_SECTIONS, type OrgSection } from "./nav-sections";
import { PortalNav } from "./PortalNav";

export { ORG_SECTIONS, type OrgSection } from "./nav-sections";

/**
 * The organisation portal's navigation (PortalNav, as DevNav). `query` ("?org=<id>" for members of several
 * organisations) keeps the chosen organisation across sections.
 */
export function OrgNav({ current, query = "" }: { current: OrgSection; query?: string }) {
  const t = useTranslations("nav");
  return (
    <PortalNav
      label={t("organisation")}
      current={current}
      query={query}
      items={ORG_SECTIONS.map(({ key, href, Icon }) => ({ key, href, Icon, label: t(key) }))}
    />
  );
}
