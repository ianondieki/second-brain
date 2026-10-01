import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";

/**
 * A card whose one link (its title) covers the whole card: the link stretches over the card, keeps no underline,
 * and the card itself shows the hover and the focus ring (the link's own outline is off). Put this on the title's
 * <a> inside a Card with `interactive`.
 */
export const cardLinkClass = "no-underline text-ink after:absolute after:inset-0 after:rounded-panel focus-visible:outline-none";

/**
 * The heading of a group inside a card (a settings card, a form's fieldset, the editor's panels): the text face at
 * 16 px, semibold; the serif is kept for the page's own h1 and h2 (p18-design-system.md, Type). One style for the role,
 * wherever the card is.
 */
export const cardHeadingClass = "font-sans text-lg font-semibold tracking-[-0.01em] text-ink";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: "article" | "div" | "section" | "li" | "fieldset";
  /** The card holds one stretched link (cardLinkClass): hover and focus show on the card. */
  interactive?: boolean;
  /** `raised` carries the card shadow; `flat` is a bordered box on the paper (compact lists); `bare` draws nothing
   *  (the same element kept in place while its content decides whether a frame is due). */
  variant?: "raised" | "flat" | "wash" | "bare";
  /** `none` for a card whose edge is drawn by its content (a lattice band, then its own padded body). */
  padding?: "none" | "sm" | "md";
  children: ReactNode;
}

const VARIANTS = {
  raised: "border border-line bg-field shadow-card",
  flat: "border border-line bg-field",
  wash: "bg-accent-wash",
  bare: "",
} as const;

/** A card (docs/platform/design/p18-design-system.md): a bordered box with the panel radius; raised cards carry the one card shadow. */
export function Card({ as: Tag = "div", variant = "raised", padding = "md", interactive = false, className, children, ...rest }: CardProps) {
  return (
    <Tag
      className={cn(
        "relative min-w-0 rounded-panel",
        VARIANTS[variant],
        padding === "md" ? "p-5" : padding === "sm" ? "p-4" : null,
        interactive &&
          "transition-[border-color,box-shadow] duration-(--motion-fast) hover:border-accent-line hover:shadow-overlay " +
            "has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/** Cards side by side: one column on phones, two from 640 px. */
export function CardGrid({ className, children, ...rest }: HTMLAttributes<HTMLUListElement> & { children: ReactNode }) {
  return (
    <ul className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2 [&>li]:min-w-0 [&>li>*]:h-full", className)} {...rest}>
      {children}
    </ul>
  );
}
