import { useLocale, useTranslations } from "next-intl";
import type { ComponentType, CSSProperties } from "react";

import { DiscoverIcon } from "@/components/discover-icons";
import { FileCheckIcon } from "@/components/icons/lucide";
import { CompaniesIcon } from "@/components/ui/icons";
import { cn } from "@/components/ui/cn";
import type { ActivityItem, ActivityKind, PublicActivity } from "@/lib/public/public-data";

const ICONS: Record<ActivityKind, ComponentType<{ className?: string }>> = {
  problem_posted: DiscoverIcon,
  version_registered: FileCheckIcon,
  brief_opened: CompaniesIcon,
};

/** The items this page knows how to say (an older page meeting a newer API skips a kind it has no words for). */
const known = (items: readonly ActivityItem[]) => items.filter((item) => Object.hasOwn(ICONS, item.kind));

/** "5 minutes ago", "2 hours ago", "yesterday": from the feed's own instant, in the page's language. */
export function ago(locale: string, at: string, now: string): string {
  const minutes = Math.max(0, Math.round((Date.parse(now) - Date.parse(at)) / 60_000));
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (minutes < 60) return format.format(-minutes, "minute");
  if (minutes < 1_440) return format.format(-Math.round(minutes / 60), "hour");
  return format.format(-Math.round(minutes / 1_440), "day");
}

function useItemWords() {
  const t = useTranslations("landing.activity");
  const locale = useLocale();
  return (item: ActivityItem, now: string) => ({
    what: t(`kind.${item.kind}`),
    where: item.county ?? t("nationwide"),
    when: ago(locale, item.at, now),
  });
}

function Item({ item, now }: { item: ActivityItem; now: string }) {
  const words = useItemWords()(item, now);
  const Icon = ICONS[item.kind];
  return (
    <li className="ticker-item">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-wash text-accent">
        <Icon className="size-[1.125rem]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3 text-xs text-ink-soft">
          <span className="truncate">{words.what}</span>
          <time dateTime={item.at} className="shrink-0 tabular-nums">
            {words.when}
          </time>
        </span>
        <span className="mt-0.5 block truncate text-sm font-semibold text-ink">{item.title ?? words.where}</span>
        {item.title ? <span className="block truncate text-xs text-ink-soft">{words.where}</span> : null}
      </span>
    </li>
  );
}

/**
 * "What's happening" (D-66): the public activity feed as a slow CSS marquee (globals.css .ticker: two copies of the row,
 * a transform loop, paused while hovered or focused; the box takes focus so a keyboard can pause it). The moving row
 * is decorative to assistive technology, which reads the same items once from a visually hidden list. Under reduced
 * motion the row stands still and scrolls sideways. `strip` is Home's compact form: on phones the three newest items
 * stand as a list instead.
 */
export function Ticker({ activity, variant = "page" }: { activity: PublicActivity; variant?: "page" | "strip" }) {
  const t = useTranslations("landing.activity");
  const words = useItemWords();
  const now = activity.generated_at;
  const items = known(activity.items);
  return (
    <div data-ticker={variant}>
      <ul aria-label={t("listLabel")} className="sr-only">
        {items.map((item) => {
          const w = words(item, now);
          return (
            <li key={item.id}>
              {item.title ? <span>{item.title}. </span> : null}
              <span>{w.what}. </span>
              <span>{w.where}. </span>
              <time dateTime={item.at}>{w.when}</time>
            </li>
          );
        })}
      </ul>
      {variant === "strip" ? (
        <ul aria-hidden="true" className="flex flex-col gap-2 sm:hidden">
          {items.slice(0, 3).map((item) => (
            <Item key={item.id} item={item} now={now} />
          ))}
        </ul>
      ) : null}
      <div tabIndex={0} role="region" aria-label={t("label")} className={cn("ticker", variant === "strip" && "max-sm:hidden")}>
        <div aria-hidden="true" className="ticker-track" style={{ "--ticker-items": items.length } as CSSProperties}>
          {[0, 1].map((copy) => (
            <ul key={copy} className="ticker-row">
              {items.map((item) => (
                <Item key={item.id} item={item} now={now} />
              ))}
            </ul>
          ))}
        </div>
      </div>
    </div>
  );
}
