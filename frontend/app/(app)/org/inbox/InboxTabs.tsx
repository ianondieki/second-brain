import Link from "next/link";
import { useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";

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
  const tabs = [
    { key: "tagged", label: t("tabTagged") },
    { key: "matches", label: t("tabMatches") },
  ] as const;
  return (
    <nav aria-label={t("tabsLabel")} className="mt-4 border-b border-line">
      <ul className="flex gap-1 overflow-x-auto">
        {tabs.map(({ key, label }) => (
          <li key={key}>
            <Link
              href={hrefs[key]}
              aria-current={key === current ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center border-b-2 px-3 font-semibold whitespace-nowrap no-underline",
                key === current ? "border-jacaranda text-jacaranda" : "border-transparent text-ink-soft hover:text-ink",
              )}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
