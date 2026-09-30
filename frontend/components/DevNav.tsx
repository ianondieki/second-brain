import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { DiscoverIcon } from "./discover-icons";
import { PortalNav } from "./PortalNav";
import { EngagementsIcon } from "./tracker/icons";
import { CompaniesIcon, HomeIcon, IdeasIcon } from "./ui/icons";

/**
 * The developer portal's sections (docs/spec/07 item 1: Home · Discover · My Ideas · Engagements · Companies, at
 * most five). Only the built ones are listed: each later screen adds its row here in the spec's order.
 */
export const DEV_SECTIONS = [
  { key: "home", href: "/dev", Icon: HomeIcon },
  { key: "discover", href: "/dev/discover", Icon: DiscoverIcon },
  { key: "ideas", href: "/dev/ideas", Icon: IdeasIcon },
  { key: "engagements", href: "/dev/engagements", Icon: EngagementsIcon },
  { key: "companies", href: "/dev/companies", Icon: CompaniesIcon },
] as const satisfies ReadonlyArray<{ key: string; href: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }>;

export type DevSection = (typeof DEV_SECTIONS)[number]["key"];

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
