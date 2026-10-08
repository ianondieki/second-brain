import { Suspense, type ReactNode } from "react";

import type { StaffRole } from "./AdminNav";
import { cn } from "./ui/cn";
import { AccountMenu } from "./AccountMenu";
import { NotificationBell, UnreadNotificationBell } from "./NotificationBell";
import { PaletteSlot } from "./palette/PaletteSlot";
import { TopBar } from "./TopBar";

export interface SignedInShellProps {
  homeHref: string;
  children: ReactNode;
  /** The portal's navigation (for example <DevNav />): bottom tabs on phones, a left rail from 1024 px. */
  nav?: ReactNode;
  /** Lists and directories use the full content width; forms and summaries keep a 36 rem column. */
  wide?: boolean;
  /** The page is the bell's own (/notifications): the bell carries aria-current="page". */
  bellCurrent?: boolean;
  /** The staff console's role, so the command palette lists the sections that role may open. */
  staffRole?: StaffRole;
}

/**
 * Signed-in screens: top bar with Search (the command palette), the notification bell and the account menu (Plan &
 * billing, Notification settings, Help, Sign out), the portal navigation when given, and one column of content.
 */
export function SignedInShell({ homeHref, children, nav, wide = false, bellCurrent = false, staffRole }: SignedInShellProps) {
  return (
    <>
      <TopBar homeHref={homeHref} sticky>
        {/* docs/spec/07 item 1: the bell, then the avatar menu, on the right of the bar; P25 puts Search before them
            (the command palette, D-67). */}
        <div className="flex min-w-0 items-center gap-1 sm:gap-2" data-top-bar-controls="">
          <PaletteSlot homeHref={homeHref} staffRole={staffRole} />
          {/* A slow count never holds the page: until it answers, the bell is there without one. */}
          <Suspense fallback={<NotificationBell count={null} current={bellCurrent} />}>
            <UnreadNotificationBell current={bellCurrent} />
          </Suspense>
          <AccountMenu />
        </div>
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
