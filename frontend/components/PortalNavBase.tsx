import type { ComponentType, SVGProps } from "react";

import type { AnchorComponent } from "./anchor";
import { cn } from "./ui/cn";

export interface PortalNavItem {
  key: string;
  href: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export interface PortalNavBaseProps {
  /** The <nav>'s accessible name ("Developer", "Organisation", "Staff console"). */
  label: string;
  /** At most five (docs/spec/07 item 1, AC-UX-1). */
  items: readonly PortalNavItem[];
  current?: string;
  /** "?org=<id>" for members of several organisations: kept on every link. */
  query?: string;
  /** A name shown above the rail from 1024 px (the staff console says whose console it is). */
  heading?: string;
  /** next/link on pages (PortalNav), a plain "a" in the route loading states (see components/anchor.ts). */
  Anchor: AnchorComponent;
}

/**
 * A portal's sections, one implementation behind DevNav, OrgNav and AdminNav (through PortalNav, which gives it
 * next/link): bottom tabs under 1024 px, a left rail
 * from 1024 px (one <nav>, restyled). The current section carries aria-current="page" and is marked by colour, weight
 * and a bar, not colour alone. The tab bar is fixed, so pages that show it keep their last control clear of it
 * (SignedInShell pads main; globals.css pads focus scrolling). With a single section there is no tab bar below
 * 1024 px: one tab only takes room on a phone.
 */
export function PortalNavBase({ label, items, current, query = "", heading, Anchor }: PortalNavBaseProps) {
  if (items.length === 0) return null;
  const tabs = items.length > 1;
  return (
    <nav
      aria-label={label}
      data-tab-bar={tabs ? "" : undefined}
      className={cn(
        tabs
          ? "fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] " +
              "lg:static lg:z-auto lg:border-0 lg:bg-transparent lg:pb-0"
          : "hidden lg:block",
        "lg:w-52 lg:shrink-0 lg:pt-16",
      )}
    >
      {heading ? <p className="hidden px-3 pb-3 text-sm font-medium text-ink-soft lg:block">{heading}</p> : null}
      <ul className="mx-auto flex max-w-md lg:max-w-none lg:flex-col lg:gap-1">
        {items.map(({ key, href, label: text, Icon }) => {
          const active = key === current;
          return (
            // flex-auto, not flex-1: tabs share the width from their labels' own widths, so a long label in bold
            // ("Engagements" when current) gets the room it needs at 360 px instead of running into its neighbour.
            <li key={key} className="min-w-0 flex-auto lg:flex-none">
              <Anchor
                href={`${href}${query}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  // Five tabs share 360 px: a size smaller below 380 px, where a two-word label (Swahili's "Mawazo
                  // yangu") may wrap onto a second line inside its own tab rather than run into the next one.
                  "relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-center text-sm whitespace-nowrap no-underline",
                  "max-[380px]:px-0.5 max-[380px]:text-xs max-[380px]:leading-tight max-[380px]:whitespace-normal sm:px-2",
                  "lg:min-h-11 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-control lg:px-3 lg:text-left lg:text-base",
                  "transition-colors duration-150 ease-out",
                  active
                    ? "font-semibold text-jacaranda lg:bg-jacaranda-wash"
                    : "font-medium text-ink-soft hover:text-ink lg:hover:bg-wash-soft",
                )}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-6 top-0 h-0.5 rounded-b bg-jacaranda lg:inset-x-auto lg:inset-y-2 lg:left-0 lg:h-auto lg:w-0.5 lg:rounded-none lg:rounded-r"
                  />
                ) : null}
                <Icon className="size-5 shrink-0" />
                <span>{text}</span>
              </Anchor>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
