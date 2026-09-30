import type { AnchorHTMLAttributes, ComponentType } from "react";

/**
 * The element a shared frame renders its links with: next/link on pages, a plain "a" in the route loading states. A
 * loading state's module graph must not import next/link: Next.js prefetches loading states for every link in view,
 * and a next/link there becomes a chunk of its own the router downloads with each prefetch (components/RouteLoading).
 */
export type AnchorComponent = "a" | ComponentType<AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }>;
