import type { ReactNode } from "react";

import { cn } from "./ui/cn";
import { SignOutButton } from "./SignOutButton";
import { TopBar } from "./TopBar";

export interface SignedInShellProps {
  homeHref: string;
  children: ReactNode;
  /** The portal's navigation (for example <DevNav />): bottom tabs on phones, a left rail from 1024 px. */
  nav?: ReactNode;
  /** Lists and directories use the full content width; forms and summaries keep a 36 rem column. */
  wide?: boolean;
}

/** Signed-in screens: top bar with Sign out, the portal navigation when given, and one column of content. */
export function SignedInShell({ homeHref, children, nav, wide = false }: SignedInShellProps) {
  return (
    <>
      <TopBar homeHref={homeHref}>
        <SignOutButton />
      </TopBar>
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
