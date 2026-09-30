import type { ReactNode } from "react";

import { cn } from "./ui/cn";
import { AccountMenu } from "./AccountMenu";
import { TopBar } from "./TopBar";

export interface SignedInShellProps {
  homeHref: string;
  children: ReactNode;
  /** The portal's navigation (for example <DevNav />): bottom tabs on phones, a left rail from 1024 px. */
  nav?: ReactNode;
  /** Lists and directories use the full content width; forms and summaries keep a 36 rem column. */
  wide?: boolean;
  /**
   * The top bar's one control: the account menu unless given. The route loading states give a still placeholder: the
   * menu is a client component, and a prefetched loading state that references it makes the router download the next
   * route's chunk that carries it (docs/spec/07 item 5, the 150 KB budget).
   */
  account?: ReactNode;
}

/**
 * Signed-in screens: top bar with the account menu (Plan & billing, Notifications, Help, Sign out), the portal
 * navigation when given, and one column of content.
 */
export function SignedInShell({ homeHref, children, nav, wide = false, account = <AccountMenu /> }: SignedInShellProps) {
  return (
    <>
      <TopBar homeHref={homeHref}>{account}</TopBar>
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
