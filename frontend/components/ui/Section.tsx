import Link from "next/link";
import { useId, type HTMLAttributes, type ReactNode } from "react";

import { standaloneLinkClass } from "./Button";
import { cn } from "./cn";
import { LinkPending } from "./LinkPending";

export interface SectionProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title: ReactNode;
  /** The heading's id (the section is labelled by it); generated when not given. */
  headingId?: string;
  headingLevel?: 2 | 3;
  /** One line under the heading. */
  description?: ReactNode;
  /** A secondary link at the end of the heading row ("See all"). */
  link?: { href: string; label: ReactNode };
  /** The heading takes focus when a change ends there (tabIndex -1, no ring: it is not a control), as PageHeader's. */
  focusable?: boolean;
  children?: ReactNode;
}

/**
 * A titled part of a page: h2 at 20 px, an optional one-line description and an optional secondary link beside the
 * heading, then its content 16 px below. No rule under the heading: the rule belongs to the rows of a list
 * (docs/platform/design/p16-design-system.md, Sections).
 */
export function Section({
  title,
  headingId,
  headingLevel = 2,
  description,
  link,
  focusable = false,
  className,
  children,
  ...rest
}: SectionProps) {
  const generated = useId();
  const id = headingId ?? generated;
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const heading = (
    <Heading
      id={id}
      tabIndex={focusable ? -1 : undefined}
      className={cn(
        "text-ink",
        headingLevel === 3 ? "text-base" : "text-lg",
        focusable && "focus:outline-none",
        description && link && "sm:col-start-1 sm:row-start-1",
      )}
    >
      {title}
    </Heading>
  );
  const secondary = link ? (
    <Link
      href={link.href}
      className={cn(standaloneLinkClass, "relative", description && "justify-self-start sm:col-start-2 sm:row-start-1")}
    >
      {link.label}
      <LinkPending className="absolute bottom-0.5 left-0" />
    </Link>
  ) : null;
  const lead = description ? (
    <p className={cn("mt-1 max-w-[62ch] text-sm text-ink-soft", link && "sm:col-start-1 sm:row-start-2")}>
      {description}
    </p>
  ) : null;
  return (
    <section aria-labelledby={id} className={className} {...rest}>
      {description && link ? (
        // Heading, description, then the link, in reading order: on a phone the link comes after the description
        // (not wedged between the heading and it); from 640 px it sits at the end of the heading row.
        <div className="grid grid-cols-1 items-baseline gap-x-6 sm:grid-cols-[minmax(0,1fr)_auto]">
          {heading}
          {lead}
          {secondary}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-x-6">
            {heading}
            {secondary}
          </div>
          {lead}
        </>
      )}
      {children ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}
