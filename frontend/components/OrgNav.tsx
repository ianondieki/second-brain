import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { InboxIcon } from "./org-icons";
import { PortalNav } from "./PortalNav";
import { EngagementsIcon } from "./tracker/icons";
import { HomeIcon } from "./ui/icons";

/**
 * The organisation portal's sections (docs/spec/07 item 1: Inbox · Engagements · Problems · Team, at most five; Home
 * holds the second-factor prompt until onboarding lands). Only the built ones are listed: each later screen adds its
 * row here in the spec's order. Same look and behaviour as DevNav.
 */
export const ORG_SECTIONS = [
  { key: "home", href: "/org", Icon: HomeIcon },
  { key: "inbox", href: "/org/inbox", Icon: InboxIcon },
  { key: "engagements", href: "/org/engagements", Icon: EngagementsIcon },
] as const satisfies ReadonlyArray<{ key: string; href: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }>;

export type OrgSection = (typeof ORG_SECTIONS)[number]["key"];

/**
 * The organisation portal's navigation (PortalNav, as DevNav). `query` ("?org=<id>" for members of several
 * organisations) keeps the chosen organisation across sections.
 */
export function OrgNav({ current, query = "" }: { current?: OrgSection; query?: string }) {
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
