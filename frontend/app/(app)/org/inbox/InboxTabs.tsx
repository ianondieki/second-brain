import { useTranslations } from "next-intl";

import { TabNav } from "@/components/ui/TabNav";

/** The Inbox's sections: two tabs of /org/inbox (`?tab=`) and the Shortlist, its own page (/org/inbox/shortlist). */
export type InboxTab = "tagged" | "matches" | "shortlist";

/** `?tab=` of the Inbox: "matches" opens Scout matches (the EM3 digest's link), anything else Sent to you. */
export function inboxTab(value: string | undefined): Exclude<InboxTab, "shortlist"> {
  return value === "matches" ? "matches" : "tagged";
}

/**
 * The Inbox's sections (docs/spec/07 item 1: Tagged us · Scout matches; P21: the organisation's Shortlist), as links,
 * so each is its own URL and works before the page's JavaScript loads. The current one carries aria-current="page" and a bar, not colour alone.
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
        { key: "shortlist", label: t("tabShortlist"), href: hrefs.shortlist },
      ]}
    />
  );
}
