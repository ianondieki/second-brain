import Link from "next/link";
import type { ComponentType, SVGProps } from "react";

import { cn } from "./ui/cn";
import { LinkPending } from "./ui/LinkPending";

export interface PortalNavItem {
  key: string;
  href: string;
  label: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export interface PortalNavProps {
  /** The <nav>'s accessible name ("Developer", "Organisation", "Staff console"). */
  label: string;
  /** At most five (docs/spec/07 item 1, AC-UX-1). */
  items: readonly PortalNavItem[];
  current?: string;
  /** "?org=<id>" for members of several organisations: kept on every link. */
  query?: string;
  /** A name shown above the rail from 1024 px (the staff console says whose console it is). */
  heading?: string;
}

/**
 * A portal's sections, one implementation behind DevNav, OrgNav and AdminNav: bottom tabs under 1024 px, a left rail
 * from 1024 px (one <nav>, restyled). The current section carries aria-current="page" and is marked by colour, weight
 * and a bar, not colour alone. The tab bar is fixed, so pages that show it keep their last control clear of it
 * (SignedInShell pads main; globals.css pads focus scrolling). With a single section there is no tab bar below
 * 1024 px: one tab only takes room on a phone.
 */
export function PortalNav({ label, items, current, query = "", heading }: PortalNavProps) {
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
              <Link
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
                    className={
                      // A fixed 32 px bar centred over the tab (not inset from both sides, which left 4 px over "Home"
                      // at 360 px); from 1024 px a 2 px bar down the rail item's left edge.
                      "absolute top-0 left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-b bg-jacaranda " +
                      "lg:inset-y-2 lg:left-0 lg:h-auto lg:w-0.5 lg:translate-x-0 lg:rounded-none lg:rounded-r"
                    }
                  />
                ) : null}
                <Icon className="size-5 shrink-0" />
                <span>{text}</span>
                {/* The tapped section's page on its way: under the label on the tab bar, at the rail item's end. */}
                <LinkPending className="absolute bottom-1 left-1/2 -translate-x-1/2 lg:static lg:ml-auto lg:translate-x-0" />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
