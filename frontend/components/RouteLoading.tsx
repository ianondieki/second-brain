import { AdminNavPlaceholder } from "./AdminNavPlaceholder";
import { DevNav, type DevSection } from "./DevNav";
import { OrgNav, type OrgSection } from "./OrgNav";
import { SignedInShell } from "./SignedInShell";
import { PageSkeleton } from "./ui/PageSkeleton";

// The loading states of the signed-in route segments (their loading.tsx files): the shell the page will render, with
// the section's navigation, around a PageSkeleton. Server components with no data: Next.js prefetches them, so a tap
// on a link shows the next screen's frame at once while its data loads (docs/platform/design/p16-design-system.md,
// Loading). The signed-in group has no layout of its own, so nothing above these reads cookies and holds the fallback
// back; the staff console's layout reads the session once, when the console is entered, and its sections' loading
// states show as staff move between them.

/** A developer portal segment, with its section current in the navigation. */
export function DevLoading({ current, wide = true }: { current: DevSection; wide?: boolean }) {
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current={current} />} wide={wide}>
      <PageSkeleton />
    </SignedInShell>
  );
}

/**
 * An organisation portal segment. A member of several organisations carries ?org=, which a loading state cannot read
 * (it has no search params); the page that replaces it links with it again.
 */
export function OrgLoading({ current, wide = true }: { current: OrgSection; wide?: boolean }) {
  return (
    <SignedInShell homeHref="/org" nav={<OrgNav current={current} />} wide={wide}>
      <PageSkeleton />
    </SignedInShell>
  );
}

/** Screens either side opens (plan and billing, settings, a problem), which have no portal navigation. */
export function AccountLoading() {
  return (
    <SignedInShell homeHref="/">
      <PageSkeleton />
    </SignedInShell>
  );
}

/**
 * A staff console segment. Its sections depend on the staff role, which only the page reads: the rail keeps its room
 * from 1024 px so nothing moves when the page arrives.
 */
export function AdminLoading({ wide = true }: { wide?: boolean }) {
  return (
    <SignedInShell homeHref="/admin" nav={<AdminNavPlaceholder />} wide={wide}>
      <PageSkeleton />
    </SignedInShell>
  );
}
