import { getTranslations } from "next-intl/server";
import type { ComponentType, SVGProps } from "react";

import type { AdminSection, StaffRole } from "@/components/AdminNav";
import { ClaimsIcon, ModerationIcon, QuizIcon, ResearchIcon } from "@/components/admin-icons";
import { DiscoverIcon } from "@/components/discover-icons";
import { BriefIcon, CalendarIcon, InboxIcon } from "@/components/org-icons";
import type { OrgSection } from "@/components/OrgNav";
import { PortalNavBase } from "@/components/PortalNavBase";
import { EngagementsIcon } from "@/components/tracker/icons";
import { CompaniesIcon, HomeIcon, IdeasIcon } from "@/components/ui/icons";

type Section = { key: string; href: string; Icon: ComponentType<SVGProps<SVGSVGElement>> };

// The portals' sections as OrgNav, DevNav and AdminNav list them (loading-nav.test.ts keeps the three lists equal to
// theirs). Repeated here because those modules import next/link, and a loading screen must import no client code.
export const LOADING_ORG: readonly Section[] = [
  { key: "home", href: "/org", Icon: HomeIcon },
  { key: "inbox", href: "/org/inbox", Icon: InboxIcon },
  { key: "engagements", href: "/org/engagements", Icon: EngagementsIcon },
  { key: "problems", href: "/org/problems", Icon: BriefIcon },
  { key: "events", href: "/org/events", Icon: CalendarIcon },
];
export const LOADING_DEV: readonly Section[] = [
  { key: "home", href: "/dev", Icon: HomeIcon },
  { key: "discover", href: "/dev/discover", Icon: DiscoverIcon },
  { key: "ideas", href: "/dev/ideas", Icon: IdeasIcon },
  { key: "engagements", href: "/dev/engagements", Icon: EngagementsIcon },
  { key: "companies", href: "/dev/companies", Icon: CompaniesIcon },
];
export const LOADING_STAFF: readonly (Section & { roles: readonly StaffRole[] })[] = [
  { key: "research", href: "/admin/research", Icon: ResearchIcon, roles: ["admin"] },
  { key: "moderation", href: "/admin/moderation", Icon: ModerationIcon, roles: ["admin", "moderator"] },
  { key: "claims", href: "/admin/claims", Icon: ClaimsIcon, roles: ["admin"] },
  { key: "quiz", href: "/admin/quiz", Icon: QuizIcon, roles: ["admin"] },
  { key: "events", href: "/admin/events", Icon: CalendarIcon, roles: ["admin", "moderator"] },
];

export type LoadingPortal =
  | { portal: "org"; current?: OrgSection }
  | { portal: "staff"; current?: AdminSection; role?: StaffRole }
  | { portal: "developer" };

/**
 * A portal's navigation as its loading screen draws it (D-67, P25): PortalNavBase, the markup behind OrgNav, DevNav
 * and AdminNav, with plain links, so the screen holds no client code and a link's prefetch of it fetches no route
 * script (REQ-UX-05's 150 KB). Its links still work (a full load) while the page is on its way.
 */
export async function LoadingNav(props: LoadingPortal) {
  const [nav, shell, admin] = await Promise.all([getTranslations("nav"), getTranslations("shell"), getTranslations("admin")]);
  const help = { href: "/help", label: shell("help") };
  if (props.portal === "staff") {
    const role = props.role ?? "admin";
    return (
      <PortalNavBase
        Anchor="a"
        help={help}
        label={admin("navLabel")}
        heading={admin("navLabel")}
        current={props.current}
        items={LOADING_STAFF.filter((s) => s.roles.includes(role)).map(({ key, href, Icon }) => ({
          key,
          href,
          Icon,
          label: admin(`nav.${key as AdminSection}`),
        }))}
      />
    );
  }
  const org = props.portal === "org";
  return (
    <PortalNavBase
      Anchor="a"
      help={help}
      label={nav(org ? "organisation" : "developer")}
      current={org ? props.current : undefined}
      items={(org ? LOADING_ORG : LOADING_DEV).map(({ key, href, Icon }) => ({ key, href, Icon, label: nav(key as Parameters<typeof nav>[0]) }))}
    />
  );
}
