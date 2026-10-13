import { getTranslations } from "next-intl/server";

/** The account menu's item look (components/AccountMenu.tsx itemClass), written here: this item renders on the server. */
const ITEM =
  "flex min-h-11 w-full items-center rounded-control px-3 font-medium text-ink no-underline hover:bg-accent-wash";

/**
 * "Team" in the account menu on organisation screens (REQ-TEN-02; docs/spec/07 item 1). The portal's tab bar holds its
 * five sections already (Home, Inbox, Engagements, Problems, Events: components/OrgNav.tsx), the most spec 07 allows,
 * so the organisation's Team sits with the organisation's other settings (Plan & billing) in the account menu, at every
 * width, and in the command palette. Server-rendered and handed to the menu as `extra`: no script of its own.
 * `homeHref` is the shell's ("/org" or "/org?org=<id>"): the chosen organisation is kept.
 */
export async function AccountMenuTeam({ homeHref }: { homeHref: string }) {
  const t = await getTranslations("shell");
  const query = homeHref.slice("/org".length);
  return (
    <li>
      <a href={`/org/team${query}`} className={ITEM} data-menu-team="">
        {t("team")}
      </a>
    </li>
  );
}

/** Whether a signed-in shell belongs to the organisation portal (its wordmark leads to /org). */
export function isOrgShell(homeHref: string): boolean {
  return homeHref === "/org" || homeHref.startsWith("/org?");
}
