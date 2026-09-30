"use client";

import { useLinkStatus } from "next/link";

import { cn } from "./cn";

/**
 * In-app navigation feedback inside a next/link (PortalNav, TabNav, Row titles, BackLink): a short accent bar that
 * shows while the tapped link's page is on its way (useLinkStatus). Always rendered at a fixed size and only its
 * opacity changes, so nothing moves; it fades in after 100 ms, so a fast navigation shows nothing; the pulse runs
 * only without reduced motion. aria-hidden: Next.js's route announcer reads the new page's title on arrival.
 * No route-level loading.tsx: a revealed Suspense fallback is held for at least ~300 ms, which made pages slower
 * (docs/platform/design/p16-design-system.md, Loading).
 */
export function LinkPending({ className }: { className?: string }) {
  const { pending } = useLinkStatus();
  return (
    <span
      aria-hidden="true"
      data-link-pending={pending ? "true" : "false"}
      className={cn(
        "pointer-events-none inline-block h-0.5 w-3 shrink-0 bg-jacaranda transition-opacity duration-150 ease-out",
        "motion-reduce:transition-none",
        pending ? "opacity-100 delay-100 motion-safe:animate-pulse" : "opacity-0",
        className,
      )}
    />
  );
}
