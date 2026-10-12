import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { cn } from "@/components/ui/cn";
import type { TeamFacts } from "@/components/tracker/model";

// "Assigned to me" (REQ-ENG-15): the organisation's Engagements list, Inbox and Board narrowed to what is assigned to
// the signed-in member, as `?assignee=me`; the Board draws this same pair of links (components/pipeline/Board.tsx). Links, so each view is its own
// address and works before any script loads; the chosen one carries aria-current and its own fill (never colour
// alone: it is also the bolder, bordered one).

/** The query value of the filter. */
export const ASSIGNED_TO_ME = "me";

/** Whether a page's `?assignee=` asks for the caller's own. */
export function assignedToMe(value: string | string[] | undefined): boolean {
  return (Array.isArray(value) ? value[0] : value) === ASSIGNED_TO_ME;
}

/** True when the item is assigned to `userId` (its team facts, as the API sends them to members). */
export function isAssignedTo(team: TeamFacts | null | undefined, userId: string): boolean {
  return team?.assignee?.user_id === userId;
}

/** The assignee's quiet line on a card: "Assigned to you", "Assigned to Wanjiru Kamau", or nothing. */
export async function assigneeLine(team: TeamFacts | null | undefined, userId: string): Promise<string | null> {
  if (!team?.assignee) return null;
  const t = await getTranslations("engagements");
  return team.assignee.user_id === userId ? t("assignedToYou") : t("assignedTo", { name: team.assignee.display_name });
}

const PILL =
  "inline-flex min-h-11 items-center rounded-full border px-4 text-sm font-semibold transition-colors " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export async function AssigneeFilter({
  mine,
  allHref,
  mineHref,
  className,
}: {
  mine: boolean;
  allHref: string;
  mineHref: string;
  className?: string;
}) {
  const t = await getTranslations("engagements");
  const items = [
    { key: "all", href: allHref, label: t("filterAll"), current: !mine },
    { key: "mine", href: mineHref, label: t("assignedToMe"), current: mine },
  ];
  return (
    <nav aria-label={t("filterLabel")} data-assignee-filter={mine ? "me" : "all"} className={className}>
      <ul className="flex flex-wrap gap-2">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              aria-current={item.current ? "page" : undefined}
              data-filter={item.key}
              className={cn(
                PILL,
                item.current
                  ? "border-accent bg-accent-wash text-ink"
                  : "border-line bg-field text-ink-soft hover:border-accent hover:text-ink",
              )}
            >
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
