import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { InboxIcon } from "./org-icons";
import { cn } from "./ui/cn";
import { HomeIcon } from "./ui/icons";

/**
 * The organisation portal's sections (docs/spec/07 item 1: Inbox · Engagements · Problems · Team, at most five; Home
 * holds the second-factor prompt until onboarding lands). Only the built ones are listed: each later screen adds its
 * row here in the spec's order. Same look and behaviour as DevNav.
 */
export const ORG_SECTIONS = [
  { key: "home", href: "/org", Icon: HomeIcon },
  { key: "inbox", href: "/org/inbox", Icon: InboxIcon },
] as const satisfies ReadonlyArray<{ key: string; href: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }>;

export type OrgSection = (typeof ORG_SECTIONS)[number]["key"];

/**
 * Bottom tabs under 1024 px, a left rail from 1024 px (one <nav>, restyled). The current section carries
 * aria-current="page" and is marked by colour, weight and a bar, not colour alone. The tab bar is fixed, so pages
 * that show it keep their last control clear of it (SignedInShell pads main; globals.css pads focus scrolling).
 * `query` ("?org=<id>" for members of several organisations) keeps the chosen organisation across sections.
 */
export function OrgNav({ current, query = "" }: { current: OrgSection; query?: string }) {
  const t = useTranslations("nav");
  return (
    <nav
      aria-label={t("organisation")}
      data-tab-bar=""
      className={
        "fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] " +
        "lg:static lg:z-auto lg:w-52 lg:shrink-0 lg:border-0 lg:bg-transparent lg:pt-16 lg:pb-0"
      }
    >
      <ul className="mx-auto flex max-w-md lg:max-w-none lg:flex-col lg:gap-1">
        {ORG_SECTIONS.map(({ key, href, Icon }) => {
          const active = key === current;
          return (
            <li key={key} className="flex-1 lg:flex-none">
              <Link
                href={`${href}${query}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-2 text-sm no-underline",
                  "lg:min-h-11 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-control lg:px-3 lg:text-base",
                  active
                    ? "font-semibold text-jacaranda lg:bg-jacaranda-wash"
                    : "font-medium text-ink-soft hover:text-ink lg:hover:bg-[color-mix(in_oklab,var(--jacaranda-wash)_55%,var(--paper))]",
                )}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-6 top-0 h-0.5 rounded-b bg-jacaranda lg:inset-x-auto lg:inset-y-2 lg:left-0 lg:h-auto lg:w-0.5 lg:rounded-none lg:rounded-r"
                  />
                ) : null}
                <Icon className="size-5 shrink-0" />
                <span>{t(key)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
