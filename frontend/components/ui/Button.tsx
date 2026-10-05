import type { ButtonHTMLAttributes, MouseEvent } from "react";

import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "danger" | "link";

// The button styles live in app/globals.css (@layer components: .btn and its variants), not in class strings here:
// every client component that renders a button would otherwise ship the same long string in its bundle (the 150 KB
// budget, D-28). Utilities a caller passes (w-auto, px-4, shrink-0) still win: Tailwind's utilities layer comes later.
const variants: Record<ButtonVariant, string> = {
  // The one primary action per screen (docs/spec/07 AC-UX-2): full width at 360 px, natural width from 640 px.
  primary: "btn btn-primary",
  secondary: "btn btn-secondary",
  // Destructive or ending steps (delete, withdraw, decline): error-coloured words and border, never filled, and never
  // the screen's primary action. Status is still carried by the words, not the colour.
  danger: "btn btn-danger",
  // Busy: quieter but still readable with a dotted underline, and hover changes nothing (globals.css).
  link: "btn btn-link",
};

/**
 * Links inside running text. The vertical padding widens the tap area to about 44 px without changing the line
 * height of the sentence around it.
 */
export const textLinkClass =
  "py-3 font-semibold text-accent underline decoration-1 hover:decoration-2 " +
  "hover:text-accent-strong";

/**
 * Links that stand on their own line (lists of links, back links, paging, empty-state actions): each gets its own
 * 44 px band (WCAG 2.2 target size), so stacked links never share or overlap a tap area.
 */
export const standaloneLinkClass =
  "inline-flex min-h-11 min-w-11 items-center font-semibold text-accent underline decoration-1 hover:decoration-2 " +
  "hover:text-accent-strong";

/**
 * A title that is a link (a row's title, a problem named inside a row): the words stay ink, with a quiet hairline
 * underline that turns to the accent on hover.
 */
export const titleLinkClass = "underline decoration-line decoration-1 underline-offset-4 hover:decoration-accent";

export function buttonClass(variant: ButtonVariant, className?: string) {
  return cn(variants[variant], className);
}

/** `data-primary` marks the screen's single primary action; Playwright asserts at most one per page. */
export function primaryMark(variant: ButtonVariant) {
  return variant === "primary" ? { "data-primary": "" } : {};
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Work in progress: the button stays focusable but ignores presses (aria-disabled, not disabled). */
  busy?: boolean;
}

export function Button({
  variant = "secondary",
  busy = false,
  type = "button",
  className,
  onClick,
  children,
  ...rest
}: ButtonProps) {
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (busy) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }
  return (
    <button
      type={type}
      className={buttonClass(variant, className)}
      aria-disabled={busy || undefined}
      onClick={handleClick}
      {...primaryMark(variant)}
      {...rest}
    >
      {children}
    </button>
  );
}
