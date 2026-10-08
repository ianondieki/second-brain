import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DevNav, type DevSection } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Skeleton, SkeletonCards, SkeletonHero, SkeletonScreen, SkeletonText } from "@/components/ui/Skeleton";

/**
 * A developer screen while it loads (P25, `loading.tsx`): the same shell, rail and top bar, and blocks shaped like
 * the screen to come; "Loading" said once to assistive technology. Image-free (a band's place is a block).
 */
export async function DevLoading({ current, wide = true, children }: { current?: DevSection; wide?: boolean; children: ReactNode }) {
  const t = await getTranslations("skeleton");
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current={current} />} wide={wide}>
      <SkeletonScreen label={t("loading")}>{children}</SkeletonScreen>
    </SignedInShell>
  );
}

/** A list screen: the hero (with tabs where the screen has them) and a grid of cards. */
export function ListSkeleton({ tabs = false, band = true, count = 4, panel = false }: { tabs?: boolean; band?: boolean; count?: number; panel?: boolean }) {
  return (
    <div className="max-w-5xl">
      <SkeletonHero tabs={tabs} />
      {panel ? <Skeleton className="mb-10 h-40 w-full max-w-4xl rounded-panel" /> : null}
      <SkeletonCards count={count} band={band} />
    </div>
  );
}

/** A detail screen: a back link, the title, a lead, then a card of facts. */
export function DetailSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="max-w-3xl">
      <Skeleton className="mb-6 h-4 w-28" />
      <Skeleton className="h-9 w-4/5 rounded-lg" />
      <Skeleton className="mt-4 h-4 w-3/5" />
      <div className="mt-10 rounded-panel border border-line bg-field p-5 sm:p-6">
        <SkeletonText lines={rows} />
      </div>
    </div>
  );
}

/** The tracker: title, the turn card, then the five stages as a line of marks (image-free, REQ-UX-05). */
export function TrackerSkeleton() {
  return (
    <div className="max-w-3xl">
      <Skeleton className="mb-6 h-4 w-28" />
      <Skeleton className="h-9 w-4/5 rounded-lg" />
      <Skeleton className="mt-4 h-4 w-2/5" />
      <div className="mt-8 rounded-panel border border-line bg-field p-5 sm:p-6">
        <Skeleton className="h-6 w-24 rounded-full" />
        <Skeleton className="mt-4 h-7 w-3/5" />
        <Skeleton className="mt-5 h-12 w-40 rounded-full" />
      </div>
      <ol className="mt-8 flex flex-col gap-6 lg:flex-row lg:gap-4" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <li key={i} className="flex flex-1 items-center gap-3">
            <Skeleton className="size-6 shrink-0 rounded-full" />
            <Skeleton className="h-4 w-24" />
          </li>
        ))}
      </ol>
    </div>
  );
}
