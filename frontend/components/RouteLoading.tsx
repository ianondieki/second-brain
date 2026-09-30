import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { AdminNavPlaceholder } from "./AdminNavPlaceholder";
import { DEV_SECTIONS, ORG_SECTIONS, type DevSection, type OrgSection } from "./nav-sections";
import { PortalNavBase } from "./PortalNavBase";
import { ShellFrame } from "./ShellFrame";
import { TopBarBase } from "./TopBarBase";
import { PageSkeleton } from "./ui/PageSkeleton";

// The loading states of the signed-in route segments (their loading.tsx files): the frame the page will render, with
// the section's navigation, around a PageSkeleton, so a tap on a link shows the next screen's frame at once while its
// data loads (docs/platform/design/p16-design-system.md, Loading). Next.js prefetches these for every link in view,
// so their module graph holds no client component and no next/link: either would become chunks the router downloads
// with each prefetch (Turbopack even merges next/link into a route's own chunk, the idea page's dialogs included),
// over the 150 KB budget (docs/spec/07 item 5). Hence the link-free bases, plain <a> links (a tap during loading is
// a full page load) and a still avatar in place of the account menu. The signed-in group has no layout of its own,
// so nothing above these reads cookies and holds the fallback back; the staff console's layout reads the session
// once, when the console is entered, and its sections' loading states show as staff move between them.

/** The account menu's room in the top bar while a page loads: the avatar, still (the menu itself comes with the page). */
function AccountPlaceholder() {
  return (
    <span aria-hidden="true" className="-mr-2 inline-flex min-h-11 items-center px-2">
      <span className="size-8 rounded-full bg-jacaranda-wash" />
    </span>
  );
}

function LoadingFrame({ homeHref, nav, wide = true }: { homeHref: string; nav?: ReactNode; wide?: boolean }) {
  return (
    <ShellFrame
      topBar={
        <TopBarBase homeHref={homeHref} Anchor="a">
          <AccountPlaceholder />
        </TopBarBase>
      }
      nav={nav}
      wide={wide}
    >
      <PageSkeleton />
    </ShellFrame>
  );
}

/** A developer portal segment, with its section current in the navigation. */
export function DevLoading({ current, wide = true }: { current: DevSection; wide?: boolean }) {
  const t = useTranslations("nav");
  const items = DEV_SECTIONS.map(({ key, href, Icon }) => ({ key, href, Icon, label: t(key) }));
  return (
    <LoadingFrame
      homeHref="/dev"
      wide={wide}
      nav={<PortalNavBase label={t("developer")} current={current} items={items} Anchor="a" />}
    />
  );
}

/**
 * An organisation portal segment. A member of several organisations carries ?org=, which a loading state cannot read
 * (it has no search params); the page that replaces it links with it again.
 */
export function OrgLoading({ current, wide = true }: { current: OrgSection; wide?: boolean }) {
  const t = useTranslations("nav");
  const items = ORG_SECTIONS.map(({ key, href, Icon }) => ({ key, href, Icon, label: t(key) }));
  return (
    <LoadingFrame
      homeHref="/org"
      wide={wide}
      nav={<PortalNavBase label={t("organisation")} current={current} items={items} Anchor="a" />}
    />
  );
}

/** Screens either side opens (plan and billing, settings, a problem), which have no portal navigation. */
export function AccountLoading() {
  return <LoadingFrame homeHref="/" wide={false} />;
}

/**
 * A staff console segment. Its sections depend on the staff role, which only the page reads: the rail keeps its room
 * from 1024 px so nothing moves when the page arrives.
 */
export function AdminLoading({ wide = true }: { wide?: boolean }) {
  return <LoadingFrame homeHref="/admin" nav={<AdminNavPlaceholder />} wide={wide} />;
}
