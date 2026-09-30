import type { ButtonHTMLAttributes, MouseEvent } from "react";

import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "danger" | "link";

const base =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-control text-base font-semibold " +
  "transition-colors duration-150 ease-out aria-disabled:cursor-progress";

const variants: Record<ButtonVariant, string> = {
  // The one primary action per screen (docs/spec/07 AC-UX-2): full width at 360 px, natural width from 640 px.
  primary:
    "w-full px-6 sm:w-auto bg-jacaranda text-on-accent hover:bg-accent-strong " +
    "aria-disabled:bg-accent-strong",
  secondary: "px-5 border border-ink-soft bg-transparent text-ink hover:bg-jacaranda-wash",
  // Destructive or ending steps (delete, withdraw, decline): error-coloured words and border, never filled, and never
  // the screen's primary action. Status is still carried by the words, not the colour.
  danger: "px-5 border border-error bg-transparent text-error hover:bg-error-wash",
  link:
    "min-h-11 min-w-11 px-0 font-medium text-jacaranda underline decoration-1 hover:decoration-2 " +
    "hover:text-accent-strong " +
    // Busy: quieter but still readable (--ink-soft, 6.8:1 on paper) with a dotted underline, and hover changes
    // nothing, so a press that would be ignored does not look available.
    "aria-disabled:text-ink-soft aria-disabled:decoration-dotted " +
    "aria-disabled:hover:text-ink-soft aria-disabled:hover:decoration-1",
};

/**
 * Links inside running text. The vertical padding widens the tap area to about 44 px without changing the line
 * height of the sentence around it.
 */
export const textLinkClass =
  "py-2.5 font-semibold text-jacaranda underline decoration-1 hover:decoration-2 " +
  "hover:text-accent-strong";

/**
 * Links that stand on their own line (lists of links, back links, paging, empty-state actions): each gets its own
 * 44 px band (WCAG 2.2 target size), so stacked links never share or overlap a tap area.
 */
export const standaloneLinkClass =
  "inline-flex min-h-11 items-center font-semibold text-jacaranda underline decoration-1 hover:decoration-2 " +
  "hover:text-accent-strong";

export function buttonClass(variant: ButtonVariant, className?: string) {
  return cn(base, variants[variant], className);
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
