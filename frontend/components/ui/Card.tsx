import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: "article" | "div" | "section" | "li";
  /** `raised` carries the card shadow; `flat` is a bordered box on the paper (compact lists). */
  variant?: "raised" | "flat" | "wash";
  padding?: "sm" | "md";
  children: ReactNode;
}

const VARIANTS = {
  raised: "border border-line bg-field shadow-card",
  flat: "border border-line bg-field",
  wash: "bg-accent-wash",
} as const;

/** A card (docs/platform/design/p18-design-system.md): a bordered box with the panel radius; raised cards carry the one card shadow. */
export function Card({ as: Tag = "div", variant = "raised", padding = "md", className, children, ...rest }: CardProps) {
  return (
    <Tag className={cn("relative min-w-0 rounded-panel", VARIANTS[variant], padding === "md" ? "p-5" : "p-4", className)} {...rest}>
      {children}
    </Tag>
  );
}

/** Cards side by side: one column on phones, two from 640 px. */
export function CardGrid({ className, children, ...rest }: HTMLAttributes<HTMLUListElement> & { children: ReactNode }) {
  return (
    <ul className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2", className)} {...rest}>
      {children}
    </ul>
  );
}
