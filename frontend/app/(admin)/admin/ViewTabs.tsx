import { TabNav } from "@/components/ui/TabNav";

export interface ViewTab {
  key: string;
  label: string;
  href: string;
}

/**
 * A console queue's views (Moderation: Open · Decided; Claims: Review · In progress · Closed) as link tabs (TabNav),
 * so each is its own address and works before the page's scripts load, like the Inbox's tabs.
 */
export function ViewTabs({ label, tabs, current }: { label: string; tabs: readonly ViewTab[]; current: string }) {
  return <TabNav label={label} items={tabs} current={current} />;
}
