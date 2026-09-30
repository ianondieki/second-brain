import { useTranslations } from "next-intl";

import { TabNav } from "@/components/ui/TabNav";

export type InboxTab = "tagged" | "matches";

/** `?tab=` of the Inbox: "matches" opens Scout matches (the EM3 digest's link), anything else Sent to you. */
export function inboxTab(value: string | undefined): InboxTab {
  return value === "matches" ? "matches" : "tagged";
}

/**
 * The Inbox's two sections (docs/spec/07 item 1: Tagged us · Scout matches), as links, so each is its own URL and works
 * before the page's JavaScript loads. The current one carries aria-current="page" and a bar, not colour alone.
 */
export function InboxTabs({ current, hrefs }: { current: InboxTab; hrefs: Record<InboxTab, string> }) {
  const t = useTranslations("scoutMatches");
  return (
    <TabNav
      label={t("tabsLabel")}
      current={current}
      className="mt-4"
      items={[
        { key: "tagged", label: t("tabTagged"), href: hrefs.tagged },
        { key: "matches", label: t("tabMatches"), href: hrefs.matches },
      ]}
    />
  );
}
