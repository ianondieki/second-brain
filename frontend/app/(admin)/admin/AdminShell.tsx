import type { ReactNode } from "react";

import { AdminNav, type AdminSection, type StaffRole } from "@/components/AdminNav";
import { SignedInShell } from "@/components/SignedInShell";

/** A staff console screen: the shared top bar, the console's own navigation and one column of content. */
export function AdminShell({
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
  return (
    <SignedInShell homeHref="/admin" nav={<AdminNav role={role} current={current} />} wide={wide}>
      {children}
    </SignedInShell>
  );
}
