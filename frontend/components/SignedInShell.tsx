import type { ReactNode } from "react";

import { AccountMenu } from "./AccountMenu";
import { ShellFrame } from "./ShellFrame";
import { TopBar } from "./TopBar";

export interface SignedInShellProps {
  homeHref: string;
  children: ReactNode;
  /** The portal's navigation (for example <DevNav />): bottom tabs on phones, a left rail from 1024 px. */
  nav?: ReactNode;
  /** Lists and directories use the full content width; forms and summaries keep a 36 rem column. */
  wide?: boolean;
}

/**
 * Signed-in screens: top bar with the account menu (Plan & billing, Notifications, Help, Sign out), the portal
 * navigation when given, and one column of content.
 */
export function SignedInShell({ homeHref, children, nav, wide = false }: SignedInShellProps) {
  return (
    <ShellFrame
      topBar={
        <TopBar homeHref={homeHref}>
          <AccountMenu />
        </TopBar>
      }
      nav={nav}
      wide={wide}
    >
      {children}
    </ShellFrame>
  );
}
