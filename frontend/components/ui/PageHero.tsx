import type { ReactNode, Ref } from "react";

import { cn } from "./cn";

export interface PageHeroProps {
  /** Where you are, in a few words ("Developer / Discover"): one per hero, sentence case, never decoration. */
  eyebrow: ReactNode;
  /** The page title (the page's one h1). */
  title: ReactNode;
  /** One sentence under the title. */
  lead?: ReactNode;
  /** The screen's one primary action (`[data-primary]`): beside the title in a wide column, full width under it on a phone. */
  action?: ReactNode;
  /** A small summary or a photograph window beside the title (under it in a narrow column). */
  aside?: ReactNode;
  /** The page's views (a TabNav): under the hero, after a hairline. */
  tabs?: ReactNode;
  titleId?: string;
  /** The title takes focus when a step changes the page (tabIndex -1, no ring: it is not a control). */
  titleRef?: Ref<HTMLHeadingElement>;
  focusable?: boolean;
  className?: string;
}

/**
 * The page language of every list and home screen (D-67, P25): a mono eyebrow saying where you are, the h1 in Fraunces
 * (balanced), a one-sentence lead (pretty), the screen's one primary action, an optional aside and the page's tabs
 * (whose hairline closes it).
 * Container-query driven (globals.css `.page-hero`), so it stacks in a narrow main column whatever the window.
 * Detail screens keep PageHeader (with its back link).
 */
export function PageHero({ eyebrow, title, lead, action, aside, tabs, titleId, titleRef, focusable = false, className }: PageHeroProps) {
  return (
    <header className={cn("page-hero", tabs ? "mb-6" : "mb-8", className)} data-page-hero="">
      <div className="page-hero-body pt-2 lg:pt-4">
        <div className="page-hero-main min-w-0">
          <div className="min-w-0">
            <p className="page-eyebrow" data-eyebrow="">
              {eyebrow}
            </p>
            <h1
              id={titleId}
              ref={titleRef}
              tabIndex={focusable ? -1 : undefined}
              className={cn("page-hero-title mt-3 [overflow-wrap:anywhere] text-ink", focusable && "focus:outline-none")}
            >
              {title}
            </h1>
            {lead ? <p className="page-hero-lead mt-3 [overflow-wrap:anywhere]">{lead}</p> : null}
          </div>
          {action ? <div className="mt-5 shrink-0 @min-[40rem]/page-hero:mt-1">{action}</div> : null}
        </div>
        {aside ? (
          <div className="page-hero-aside min-w-0" data-page-hero-aside="">
            {aside}
          </div>
        ) : null}
      </div>
      {/* The tabs' own hairline (TabNav) closes the hero: a line under it only when tabs follow. */}
      {tabs ? <div className="mt-7">{tabs}</div> : null}
    </header>
  );
}
