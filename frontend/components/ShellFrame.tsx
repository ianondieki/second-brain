import type { ReactNode } from "react";

import { cn } from "./ui/cn";

export interface ShellFrameProps {
  /** The top bar (TopBar with the account menu on a page). */
  topBar: ReactNode;
  children: ReactNode;
  /** The portal's navigation (for example <DevNav />): bottom tabs on phones, a left rail from 1024 px. */
  nav?: ReactNode;
  /** Lists and directories use the full content width; forms and summaries keep a 36 rem column. */
  wide?: boolean;
}

/**
 * The signed-in frame: the top bar it is given, the portal navigation when given, and one column of content. It
 * imports no client component and no next/link: SignedInShell gives it the top bar with the account menu, and the
 * route loading states a still one (components/RouteLoading.tsx).
 */
export function ShellFrame({ topBar, children, nav, wide = false }: ShellFrameProps) {
  return (
    <>
      {topBar}
      <div className="mx-auto flex w-full max-w-6xl flex-1 lg:gap-10 lg:px-6">
        {nav}
        <main
          id="main"
          tabIndex={-1}
          className={cn(
            "w-full min-w-0 flex-1 px-4 pt-8 focus:outline-none sm:px-6 lg:px-0 lg:pt-16",
            // Room for the fixed tab bar (56 px + the safe area) under 1024 px.
            nav ? "pb-28 lg:pb-16" : "pb-16",
          )}
        >
          <div className={wide ? undefined : "max-w-xl"}>{children}</div>
        </main>
      </div>
    </>
  );
}
