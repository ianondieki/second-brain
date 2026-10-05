import Link from "next/link";
import { useId, type HTMLAttributes, type ReactNode } from "react";

import { standaloneLinkClass } from "./Button";
import { cardHeadingClass } from "./Card";
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
  /** `card` inside a card: the card heading (sans, 16 px, semibold) instead of the page's serif section heading. */
  headingStyle?: "display" | "card";
  children?: ReactNode;
}

/**
 * A titled part of a page: h2 at 24 px in the display face, an optional one-line description and an optional secondary link beside the
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
  headingStyle = "display",
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
        "text-ink sm:col-start-1 sm:row-start-1",
        headingStyle === "card" ? cardHeadingClass : headingLevel === 3 ? "text-lg" : "text-xl",
        focusable && "focus:outline-none",
      )}
    >
      {title}
    </Heading>
  );
  const lead = description ? (
    <p className="mt-1 max-w-[62ch] text-sm text-ink-soft sm:col-start-1 sm:row-start-2">{description}</p>
  ) : null;
  const secondary = link ? (
    <Link href={link.href} className={cn(standaloneLinkClass, "relative justify-self-start sm:col-start-2 sm:row-start-1")}>
      {link.label}
      <LinkPending className="absolute bottom-0.5 left-0" />
    </Link>
  ) : null;
  return (
    <section aria-labelledby={id} className={className} {...rest}>
      {/* One layout whatever the combination (ux-reviewer P18 round 1): reading order heading, description, link; on a
          phone they stack in that order, from 640 px the link ends the heading row and the description sits under it. */}
      <div className="grid grid-cols-1 items-baseline gap-x-6 sm:grid-cols-[minmax(0,1fr)_auto]">
        {heading}
        {lead}
        {secondary}
      </div>
      {children ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}
