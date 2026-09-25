import type { ReactNode } from "react";

import { SignOutButton } from "./SignOutButton";
import { TopBar } from "./TopBar";

/** Signed-in placeholder screens (Phase 1): top bar with Sign out, one column of content. */
export function SignedInShell({ homeHref, children }: { homeHref: string; children: ReactNode }) {
  return (
    <>
      <TopBar homeHref={homeHref}>
        <SignOutButton />
      </TopBar>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16">
        <div className="max-w-xl">{children}</div>
      </main>
    </>
  );
}
