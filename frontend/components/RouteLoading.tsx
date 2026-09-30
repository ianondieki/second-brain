import { AdminNavPlaceholder } from "./AdminNavPlaceholder";
import { DevNav, type DevSection } from "./DevNav";
import { OrgNav, type OrgSection } from "./OrgNav";
import { SignedInShell, type SignedInShellProps } from "./SignedInShell";
import { PageSkeleton } from "./ui/PageSkeleton";

// The loading states of the signed-in route segments (their loading.tsx files): the shell the page will render, with
// the section's navigation, around a PageSkeleton. Server components with no data and no client component: Next.js
// prefetches them for every link in view, and a client component here (the account menu) would make it download each
// linked route's chunk that carries it; the top bar holds a still placeholder instead. A tap on a link shows the next
// screen's frame at once while its data loads (docs/platform/design/p16-design-system.md, Loading). The signed-in
// group has no layout of its own, so nothing above these reads cookies and holds the fallback back; the staff
// console's layout reads the session once, when the console is entered, and its sections' loading states show as
// staff move between them.

/** The account menu's room in the top bar while a page loads: the avatar, still (the menu itself comes with the page). */
function AccountPlaceholder() {
  return (
    <span aria-hidden="true" className="-mr-2 inline-flex min-h-11 items-center px-2">
      <span className="size-8 rounded-full bg-jacaranda-wash" />
    </span>
  );
}

function LoadingShell({ children, ...shell }: Omit<SignedInShellProps, "account">) {
  return (
    <SignedInShell {...shell} account={<AccountPlaceholder />}>
      {children}
    </SignedInShell>
  );
}

/** A developer portal segment, with its section current in the navigation. */
export function DevLoading({ current, wide = true }: { current: DevSection; wide?: boolean }) {
  return (
    <LoadingShell homeHref="/dev" nav={<DevNav current={current} />} wide={wide}>
      <PageSkeleton />
    </LoadingShell>
  );
}

/**
 * An organisation portal segment. A member of several organisations carries ?org=, which a loading state cannot read
 * (it has no search params); the page that replaces it links with it again.
 */
export function OrgLoading({ current, wide = true }: { current: OrgSection; wide?: boolean }) {
  return (
    <LoadingShell homeHref="/org" nav={<OrgNav current={current} />} wide={wide}>
      <PageSkeleton />
    </LoadingShell>
  );
}

/** Screens either side opens (plan and billing, settings, a problem), which have no portal navigation. */
export function AccountLoading() {
  return (
    <LoadingShell homeHref="/">
      <PageSkeleton />
    </LoadingShell>
  );
}

/**
 * A staff console segment. Its sections depend on the staff role, which only the page reads: the rail keeps its room
 * from 1024 px so nothing moves when the page arrives.
 */
export function AdminLoading({ wide = true }: { wide?: boolean }) {
  return (
    <LoadingShell homeHref="/admin" nav={<AdminNavPlaceholder />} wide={wide}>
      <PageSkeleton />
    </LoadingShell>
  );
}
