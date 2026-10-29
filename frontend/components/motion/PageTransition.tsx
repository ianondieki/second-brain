"use client";

import { usePathname } from "next/navigation";
import { ViewTransition, type ReactNode } from "react";

// The App Router's React has <ViewTransition>; a React without it (the test runner's stable release) renders the
// content as it is.
const Transition: typeof ViewTransition | undefined = ViewTransition;

/**
 * A route change cross-fades the page (D-67, P25): React's <ViewTransition> around a portal's pages, keyed by the
 * path, so leaving one address and arriving at the next are an exit and an enter that the browser's View Transitions
 * API animates (the App Router runs every navigation as a transition). It sits in the portal's layout, above every
 * page's own DOM: React animates a boundary only when no newly inserted element encloses it. Both sides fade in the
 * same 180 ms (globals.css `.page-exit`, `.page-enter`), so the parts that do not change (the top bar, the rail) stay
 * put; the nav's current pill glides on its own (`nav-current`). Updates inside a page (a filter, a form) and a
 * change of query only do not animate (`default="none"`, the key is the path). Nothing moves under reduced motion,
 * and a browser without the API simply swaps.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (!Transition) return <>{children}</>;
  return (
    <Transition key={pathname} enter="page-enter" exit="page-exit" default="none">
      {children}
    </Transition>
  );
}
