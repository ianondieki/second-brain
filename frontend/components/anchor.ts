import type { AnchorHTMLAttributes, ComponentType } from "react";

/**
 * The element the top bar renders its home link with: next/link on pages (TopBar), a plain "a" on the not-found
 * screen, whose tree Next.js embeds in every page's payload and which therefore holds no client code.
 */
export type AnchorComponent = "a" | ComponentType<AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }>;
