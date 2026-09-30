import { Children, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";
import { noticeBox, noticeIconTone, noticeTone, type NoticeTone } from "./notice";
import { AlertIcon, CheckIcon, InfoIcon } from "./status-icons";

export type CalloutTone = NoticeTone;

export interface CalloutProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  tone?: CalloutTone;
  /** A short line in bold above the words (the whose-turn banner's headline). */
  title?: ReactNode;
  /** The title's id, for an aria-labelledby on this callout or elsewhere. */
  titleId?: string;
  /** The whose-turn banner's headline reads at the section-title size; everything else stays at body size. */
  titleSize?: "base" | "lg";
  /** A drawn mark in place of the tone's icon (decorative: the words carry the meaning). */
  icon?: ReactNode;
  /** A callout that names a region (the whose-turn banner) is a <section>; a plain note is a <div>. */
  as?: "div" | "section" | "aside";
  children?: ReactNode;
}

const ICONS = { error: AlertIcon, info: InfoIcon, ok: CheckIcon, neutral: InfoIcon } as const;

/**
 * A static notice that is part of the page from the start: 1 px tone border, tone wash, an icon and words
 * (docs/platform/design/p16-design-system.md, Notices). It has no live role: nothing is announced when the page
 * loads. Notices that appear because something happened are an Alert, which shares these tones.
 */
export function Callout({
  tone = "info",
  title,
  titleId,
  titleSize = "base",
  icon,
  as: Tag = "div",
  className,
  children,
  ...rest
}: CalloutProps) {
  const Icon = ICONS[tone];
  return (
    <Tag data-callout={tone} className={cn(noticeBox, noticeTone[tone], className)} {...rest}>
      {icon ?? <Icon className={cn("mt-0.5 size-5 shrink-0", noticeIconTone[tone])} />}
      <div className="min-w-0 flex-1">
        {title ? (
          <p id={titleId} className={cn("font-semibold text-ink", titleSize === "lg" && "text-lg")}>
            {title}
          </p>
        ) : null}
        {Children.toArray(children).length > 0 ? (
          <div className={cn("flex flex-col gap-1", Boolean(title) && "mt-1")}>{children}</div>
        ) : null}
      </div>
    </Tag>
  );
}
