import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import { DiscoverIcon } from "./discover-icons";
import { EngagementsIcon } from "./tracker/icons";
import { cn } from "./ui/cn";
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

/**
 * Bottom tabs under 1024 px, a left rail from 1024 px (one <nav>, restyled). The current section carries
 * aria-current="page" and is marked by colour, weight and a bar, not colour alone. The tab bar is fixed, so pages
 * that show it keep their last control clear of it (SignedInShell pads main; globals.css pads focus scrolling).
 */
export function DevNav({ current }: { current: DevSection }) {
  const t = useTranslations("nav");
  return (
    <nav
      aria-label={t("developer")}
      data-tab-bar=""
      className={
        "fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] " +
        "lg:static lg:z-auto lg:w-52 lg:shrink-0 lg:border-0 lg:bg-transparent lg:pt-16 lg:pb-0"
      }
    >
      <ul className="mx-auto flex max-w-md lg:max-w-none lg:flex-col lg:gap-1">
        {DEV_SECTIONS.map(({ key, href, Icon }) => {
          const active = key === current;
          return (
            <li key={key} className="min-w-0 flex-1 lg:flex-none">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  // Five tabs share 360 px: a size smaller below 380 px, where a two-word label (Swahili's "Mawazo
                  // yangu") may wrap onto a second line inside its own tab rather than run into the next one.
                  "relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-center text-sm whitespace-nowrap no-underline",
                  "max-[380px]:px-0.5 max-[380px]:text-xs max-[380px]:leading-tight max-[380px]:whitespace-normal sm:px-2",
                  "lg:min-h-11 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-control lg:px-3 lg:text-left lg:text-base",
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
