import type { ReactNode } from "react";

import { AccountMenuScope } from "@/components/AccountMenu";
import { AdminNav, type AdminSection, type StaffRole } from "@/components/AdminNav";
import { SignedInShell } from "@/components/SignedInShell";

import { staffContext } from "./staff";

/**
 * A staff console screen: the shared top bar, the console's own navigation and one column of content. A staff-only
 * account (no organisation of its own) has no plan to show, so its account menu leaves out Plan & billing.
 */
export async function AdminShell({
  role,
  current,
  wide = false,
  children,
}: {
  role: StaffRole;
  current?: AdminSection;
  wide?: boolean;
  children: ReactNode;
}) {
  const { me } = await staffContext(); // cached per request: the layout and the page made this call already
  return (
    <AccountMenuScope billing={me.memberships.length > 0}>
      <SignedInShell homeHref="/admin" nav={<AdminNav role={role} current={current} />} wide={wide}>
        {children}
      </SignedInShell>
    </AccountMenuScope>
  );
}
