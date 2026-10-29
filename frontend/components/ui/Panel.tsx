import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  /** "field": a bordered white box (the assistant panel); "wash": the accent wash without a border (the auth side panel). */
  variant?: "field" | "wash";
  as?: "div" | "section" | "aside";
  children: ReactNode;
}

const variants = {
  field: "border border-line bg-field p-5 sm:p-6",
  wash: "bg-accent-wash p-6 lg:p-8",
} as const;

/**
 * The one bordered, rounded box of a screen (docs/platform/design/p16-design-system.md, Panels): a side panel or a
 * tool panel, never a page's structure and never nested.
 */
export function Panel({ variant = "field", as: Tag = "div", className, children, ...rest }: PanelProps) {
  return (
    <Tag className={cn("rounded-panel", variants[variant], className)} {...rest}>
      {children}
    </Tag>
  );
}
