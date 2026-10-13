import { getTranslations } from "next-intl/server";

import { TabNav } from "@/components/ui/TabNav";

export const VIEWS = ["list", "calendar", "board"] as const;
export type View = (typeof VIEWS)[number];

/** `?view=` read for a portal: the list unless a view this portal has is named (the developer has no board). */
export function pickView(requested: string | string[] | undefined, board: boolean): View {
  const value = Array.isArray(requested) ? requested[0] : requested;
  if (value === "calendar") return "calendar";
  if (value === "board" && board) return "board";
  return "list";
}

/** The address of a view, the other query values (the organisation, a month) kept; the list is the bare path. */
export function viewHref(basePath: string, view: View, keep: Record<string, string | undefined> = {}): string {
  const params = new URLSearchParams();
  if (view !== "list") params.set("view", view);
  for (const [key, value] of Object.entries(keep)) if (value) params.set(key, value);
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

/**
 * The Engagements page's views as tabs under its PageHero (P27; docs/spec/07 item 1: views of one nav item, never new
 * ones): List (the default), Calendar, and for an organisation Board. Links, so each view is its own address and works
 * before any script; the organisation's `?org=` travels with them.
 */
export async function EngagementTabs({
  basePath,
  current,
  board = false,
  org,
}: {
  basePath: string;
  current: View;
  board?: boolean;
  /** The organisation's id when the person has several (`?org=`). */
  org?: string;
}) {
  const t = await getTranslations("engagements");
  const views: View[] = board ? ["list", "calendar", "board"] : ["list", "calendar"];
  return (
    <TabNav
      label={t("tabsLabel")}
      current={current}
      items={views.map((view) => ({ key: view, label: t(`tab.${view}`), href: viewHref(basePath, view, { org }) }))}
    />
  );
}
