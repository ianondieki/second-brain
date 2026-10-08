import type { CSSProperties, ReactNode } from "react";

import { cn } from "./cn";

/**
 * A block standing in for content still on its way (D-67, P25): the paper-deep layer with a slow sweep of light, which
 * stands still under reduced motion (globals.css `.skeleton`). Decorative: the loading screen that uses it says
 * "Loading" once, for assistive technology (SkeletonScreen).
 */
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <span aria-hidden="true" className={cn("skeleton", className)} style={style} data-skeleton="" />;
}

/** Lines of text: the last one shorter, as a paragraph ends. */
export function SkeletonText({ lines = 2, className }: { lines?: number; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === lines - 1 && lines > 1 ? "w-2/3" : "w-full")} />
      ))}
    </span>
  );
}

/** PageHero's shape: the eyebrow, a two-line title, the lead and the primary action's pill. */
export function SkeletonHero({ action = true, tabs = false }: { action?: boolean; tabs?: boolean }) {
  return (
    <div aria-hidden="true" className="page-hero mb-8" data-skeleton-hero="">
      <div className="page-hero-body pt-2 lg:pt-4">
        <div className="page-hero-main">
          <div className="min-w-0 flex-1">
            <Skeleton className="h-3 w-36" />
            <Skeleton className="mt-4 h-9 w-4/5 max-w-[28rem] rounded-lg" />
            <Skeleton className="mt-4 h-4 w-full max-w-[34rem]" />
          </div>
          {action ? <Skeleton className="mt-5 h-12 w-full rounded-full sm:w-40 @min-[40rem]/page-hero:mt-1" /> : null}
        </div>
      </div>
      {tabs ? (
        <div className="mt-7 flex gap-4 border-b border-line pb-3">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-14" />
        </div>
      ) : null}
    </div>
  );
}

/** A grid of cards: an optional photograph band, a title, two lines of meta, a footer line. */
export function SkeletonCards({ count = 3, band = false }: { count?: number; band?: boolean }) {
  return (
    <ul aria-hidden="true" className="card-grid" data-skeleton-cards="">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="rounded-panel border border-line bg-field p-5">
          {band ? <Skeleton className="-mx-5 -mt-5 mb-4 h-16 rounded-t-panel rounded-b-none" /> : null}
          <Skeleton className="h-5 w-4/5" />
          <SkeletonText lines={2} className="mt-3" />
          <Skeleton className="mt-5 h-6 w-28 rounded-full" />
        </li>
      ))}
    </ul>
  );
}

/**
 * A loading screen's frame (for `loading.tsx`): one polite "Loading" for assistive technology, then the shapes of
 * the page to come.
 */
export function SkeletonScreen({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div aria-busy="true" data-skeleton-screen="">
      <p role="status" className="sr-only">
        {label}
      </p>
      {children}
    </div>
  );
}
