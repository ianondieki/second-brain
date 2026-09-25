import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps, MouseEvent } from "react";

import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "link";

const base =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-control text-base font-semibold " +
  "transition-colors duration-150 ease-out aria-disabled:cursor-progress";

const variants: Record<ButtonVariant, string> = {
  // The one primary action per screen (docs/spec/07 AC-UX-2): full width at 360 px, natural width from 640 px.
  primary:
    "w-full px-6 sm:w-auto bg-jacaranda text-white hover:bg-[color-mix(in_oklab,var(--jacaranda)_84%,var(--ink))] " +
    "aria-disabled:bg-[color-mix(in_oklab,var(--jacaranda)_84%,var(--ink))]",
  secondary: "px-5 border border-ink-soft bg-transparent text-ink hover:bg-jacaranda-wash",
  link:
    "min-h-11 px-0 font-medium text-jacaranda underline decoration-1 hover:decoration-2 " +
    "hover:text-[color-mix(in_oklab,var(--jacaranda)_84%,var(--ink))]",
};

/**
 * Links inside running text. The vertical padding widens the tap area to about 44 px without changing the line
 * height of the sentence around it.
 */
export const textLinkClass =
  "py-2.5 font-semibold text-jacaranda underline decoration-1 hover:decoration-2 " +
  "hover:text-[color-mix(in_oklab,var(--jacaranda)_84%,var(--ink))]";

export function buttonClass(variant: ButtonVariant, className?: string) {
  return cn(base, variants[variant], className);
}

/** `data-primary` marks the screen's single primary action; Playwright asserts at most one per page. */
function primaryMark(variant: ButtonVariant) {
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

export interface ButtonLinkProps extends ComponentProps<typeof Link> {
  variant?: ButtonVariant;
}

/** A navigation that looks like a button (for example "Create an account" on the landing page). */
export function ButtonLink({ variant = "secondary", className, ...rest }: ButtonLinkProps) {
  return <Link className={buttonClass(variant, className)} {...primaryMark(variant)} {...rest} />;
}
