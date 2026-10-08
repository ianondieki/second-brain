import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import type { components } from "@/lib/api/schema";

import { ClaimsIcon, ModerationIcon, QuizIcon, ResearchIcon } from "./admin-icons";
import { CalendarIcon } from "./org-icons";
import { PortalNav } from "./PortalNav";

export type StaffRole = components["schemas"]["StaffRole"];

/**
 * The staff console's sections (REQ-ADM-01; docs/spec/07 item 1: "Admin is a separate console", at most five), each
 * with the staff roles the API admits to it (docs/spec/03; bridge/admin/deps.py): a section is listed only for those
 * roles. Research, Claims and Quiz (REQ-DEV-01) are the staff admin's; Moderation and Events (REQ-DEV-02, the fifth and
 * last) are the staff admin's and the moderator's. Support has no section yet (the console home tells them so).
 */
export const ADMIN_SECTIONS = [
  { key: "research", href: "/admin/research", Icon: ResearchIcon, roles: ["admin"] },
  { key: "moderation", href: "/admin/moderation", Icon: ModerationIcon, roles: ["admin", "moderator"] },
  { key: "claims", href: "/admin/claims", Icon: ClaimsIcon, roles: ["admin"] },
  { key: "quiz", href: "/admin/quiz", Icon: QuizIcon, roles: ["admin"] },
  { key: "events", href: "/admin/events", Icon: CalendarIcon, roles: ["admin", "moderator"] },
] as const satisfies ReadonlyArray<{
  key: string;
  href: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  roles: readonly StaffRole[];
}>;

export type AdminSection = (typeof ADMIN_SECTIONS)[number]["key"];

/** The sections a staff role may open, in the console's order. */
export function adminSections(role: StaffRole) {
  return ADMIN_SECTIONS.filter((section) => (section.roles as readonly StaffRole[]).includes(role));
}

/**
 * The staff console's navigation (PortalNav, as DevNav and OrgNav), with the console's name above the rail and only
 * the sections the role may open. With a single section there is no tab bar below 1024 px (the console home opens
 * that section).
 */
export function AdminNav({ current, role }: { current?: AdminSection; role: StaffRole }) {
  const t = useTranslations("admin");
  const shell = useTranslations("shell");
  return (
    <PortalNav
      help={{ href: "/help", label: shell("help") }}
      label={t("navLabel")}
      heading={t("navLabel")}
      current={current}
      items={adminSections(role).map(({ key, href, Icon }) => ({ key, href, Icon, label: t(`nav.${key}`) }))}
    />
  );
}
