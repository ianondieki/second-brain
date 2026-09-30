import type { ComponentType, SVGProps } from "react";

import { DiscoverIcon } from "./discover-icons";
import { InboxIcon } from "./org-icons";
import { EngagementsIcon } from "./tracker/icons";
import { CompaniesIcon, HomeIcon, IdeasIcon } from "./ui/icons";

// The portals' sections in a module of their own, without next/link, so the route loading states can list them
// (components/anchor.ts). DevNav and OrgNav re-export them.

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
