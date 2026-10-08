import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { TopBarBase } from "@/components/TopBarBase";
import { Skeleton, SkeletonCards, SkeletonHero, SkeletonScreen, SkeletonText } from "@/components/ui/Skeleton";

/** The shapes a loading screen can take, after the page it stands in for (D-67, P25). */
export type LoadingShape = "home" | "cards" | "list" | "table" | "detail" | "form";

/**
 * A signed-in route's loading screen (`loading.tsx`): the page's frame as SignedInShell draws it (the top bar, the
 * portal's navigation and the main column, so nothing jumps when the page arrives) around skeletons shaped like it,
 * with one polite "Loading…" for assistive technology. Search and the account menu stand in as their shapes: the
 * frame holds no client component of the app's own, so a link's prefetch of this screen fetches no route script
 * (the 150 KB budget, REQ-UX-05). Server-rendered, no API call, so it paints at once.
 */
export async function PortalLoading({
  homeHref,
  nav,
  shape,
  tabs = false,
  action = true,
}: {
  homeHref: string;
  nav?: ReactNode;
  shape: LoadingShape;
  /** The page has tabs under its hero. */
  tabs?: boolean;
  /** The page has a primary action in its hero. */
  action?: boolean;
}) {
  const t = await getTranslations("portal");
  return (
    <LoadingFrame homeHref={homeHref} nav={nav}>
      <SkeletonScreen label={t("loading")}>
        <div className="max-w-5xl" data-loading-shape={shape}>
          {shape === "home" ? (
            <>
              <Skeleton className="h-60 w-full rounded-[1.5rem] sm:h-66" />
              <ul aria-hidden="true" className="mt-10 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
                {[0, 1, 2, 3].map((i) => (
                  <li key={i} className="rounded-panel border border-line bg-field p-4 sm:p-5">
                    <Skeleton className="h-3.5 w-20" />
                    <Skeleton className="mt-3 h-7 w-12" />
                    <Skeleton className="mt-3 h-3.5 w-24" />
                  </li>
                ))}
              </ul>
              <Skeleton className="mt-12 h-6 w-48" />
              <Skeleton className="mt-4 h-44 w-full rounded-panel" />
            </>
          ) : shape === "detail" || shape === "form" ? (
            <div className="max-w-3xl">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="mt-5 h-9 w-4/5 rounded-lg" />
              <SkeletonText lines={2} className="mt-4 max-w-[34rem]" />
              <div aria-hidden="true" className="mt-10 flex flex-col gap-6 rounded-panel border border-line bg-field p-5 sm:p-6">
                {(shape === "form" ? [0, 1, 2, 3] : [0, 1]).map((i) => (
                  <span key={i} className="flex flex-col gap-2">
                    <Skeleton className="h-3.5 w-32" />
                    <Skeleton className={shape === "form" ? "h-11 w-full rounded-[10px]" : "h-16 w-full"} />
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <>
              <SkeletonHero action={action} tabs={tabs} />
              {shape === "cards" ? (
                <SkeletonCards count={4} band />
              ) : shape === "table" ? (
                <div aria-hidden="true" className="rounded-panel border border-line bg-field px-4 py-3 sm:px-6">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span key={i} className="flex items-center gap-6 border-t border-line py-4 first:border-t-0">
                      <Skeleton className="h-4 w-2/5" />
                      <Skeleton className="h-4 w-1/5" />
                      <Skeleton className="ml-auto h-6 w-24 rounded-full" />
                    </span>
                  ))}
                </div>
              ) : (
                <div aria-hidden="true" className="max-w-3xl">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span key={i} className="flex items-start gap-4 border-t border-line py-5">
                      <Skeleton className="size-10 shrink-0 rounded-full" />
                      <span className="flex flex-1 flex-col gap-2">
                        <Skeleton className="h-4 w-3/5" />
                        <Skeleton className="h-3.5 w-2/5" />
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </SkeletonScreen>
    </LoadingFrame>
  );
}

/** SignedInShell's frame with the shapes of Search and the account menu (decorative) and the bell without a count. */
async function LoadingFrame({ homeHref, nav, children }: { homeHref: string; nav?: ReactNode; children: ReactNode }) {
  return (
    <>
      <TopBarBase homeHref={homeHref} Anchor="a" sticky>
        <div aria-hidden="true" className="flex min-w-0 items-center gap-1 sm:gap-2" data-top-bar-controls="">
          <Skeleton className="size-11 rounded-full sm:h-11 sm:w-[clamp(12rem,26vw,19rem)]" />
          <Skeleton className="size-11 rounded-full" />
          <Skeleton className="size-11 rounded-full sm:w-28" />
        </div>
      </TopBarBase>
      <div className="mx-auto flex w-full max-w-6xl flex-1 lg:gap-10 lg:px-6">
        {nav}
        <main
          id="main"
          tabIndex={-1}
          className={`w-full min-w-0 flex-1 px-4 pt-8 focus:outline-none sm:px-6 lg:px-0 lg:pt-16 ${nav ? "pb-28 lg:pb-16" : "pb-16"}`}
        >
          {children}
        </main>
      </div>
    </>
  );
}
