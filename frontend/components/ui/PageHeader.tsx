import type { ReactNode, Ref } from "react";

import { BackLink } from "./BackLink";
import { cn } from "./cn";

export interface PageHeaderProps {
  /** The page title (the page's one h1). */
  title: ReactNode;
  /** One sentence under the title. */
  lead?: ReactNode;
  /** The link back to where the page was opened from, above the title. */
  back?: { href: string; label: ReactNode };
  /** The screen's primary action (one per screen): under the lead on phones, beside the title from 640 px. */
  action?: ReactNode;
  titleId?: string;
  /** The title takes focus when a step changes the page (tabIndex -1, no ring: it is not a control). */
  titleRef?: Ref<HTMLHeadingElement>;
  focusable?: boolean;
  /** Anything that belongs to the title, such as a status line, under the lead. */
  children?: ReactNode;
  className?: string;
}

/**
 * A page's header: optional back link, the h1 at one size (25 px at 360, 31 px from 1024), one-sentence lead and the
 * primary action (docs/platform/design/p16-design-system.md, Page header).
 */
export function PageHeader({
  title,
  lead,
  back,
  action,
  titleId,
  titleRef,
  focusable = false,
  children,
  className,
}: PageHeaderProps) {
  return (
    <>
      {back ? <BackLink href={back.href}>{back.label}</BackLink> : null}
      <header className={cn("flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8", className)}>
        <div className="min-w-0">
          <h1
            id={titleId}
            ref={titleRef}
            tabIndex={focusable ? -1 : undefined}
            className={cn("text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl", focusable && "focus:outline-none")}
          >
            {title}
          </h1>
          {lead ? <p className="mt-2 max-w-[62ch] text-ink-soft [overflow-wrap:anywhere]">{lead}</p> : null}
          {children}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
    </>
  );
}
