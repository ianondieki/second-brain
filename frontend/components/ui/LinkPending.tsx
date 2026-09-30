"use client";

import { useLinkStatus } from "next/link";

import { cn } from "./cn";

/**
 * In-app navigation feedback inside a next/link (PortalNav, TabNav, Row titles, BackLink): a short accent bar (24 × 3
 * px, P16-C1: large enough to notice) that shows while the tapped link's page is on its way (useLinkStatus). Always rendered at a fixed size and only its
 * opacity changes, so nothing moves; it fades in after 100 ms, so a fast navigation shows nothing; the pulse runs
 * only without reduced motion. aria-hidden: Next.js's route announcer reads the new page's title on arrival.
 * No route-level loading.tsx: a revealed Suspense fallback is held for at least ~300 ms, which made pages slower
 * (docs/platform/design/p16-design-system.md, Loading).
 */
export function LinkPending({ className, tone = "accent" }: { className?: string; tone?: "accent" | "current" }) {
  const { pending } = useLinkStatus();
  return (
    <span
      aria-hidden="true"
      data-link-pending={pending ? "true" : "false"}
      className={cn(
        // "current" on a filled primary button: the bar takes the button's own text colour, visible on the accent.
        "pointer-events-none inline-block h-[3px] w-6 shrink-0 transition-opacity duration-150 ease-out",
        tone === "current" ? "bg-current" : "bg-jacaranda",
        "motion-reduce:transition-none",
        pending ? "opacity-100 delay-100 motion-safe:animate-pulse" : "opacity-0",
        className,
      )}
    />
  );
}
