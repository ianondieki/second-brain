import { getTranslations } from "next-intl/server";

import { EngagementRow } from "./EngagementRow";
import { awaitsMe, type Party, type Summary } from "./model";

/**
 * The engagements in two groups: those waiting on the viewer's side first ("Needs you" or "Needs us"), then the rest,
 * each newest change first as the API sends them.
 */
export async function EngagementList({
  items,
  mine,
  basePath,
  query = "",
}: {
  items: Summary[];
  mine: Party;
  basePath: string;
  /** "?org=<id>" to keep on the rows' links, else "". */
  query?: string;
}) {
  const t = await getTranslations("tracker");
  const waiting = items.filter((item) => awaitsMe(item, mine));
  const rest = items.filter((item) => !awaitsMe(item, mine));
  const groups = [
    { key: "needs", title: mine === "developer" ? t("needsYou") : t("needsUs"), items: waiting },
    { key: "rest", title: t("others"), items: rest },
  ].filter((group) => group.items.length > 0);
  return (
    <div className="flex flex-col gap-10">
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`engagements-${group.key}`} data-group={group.key}>
          <h2 id={`engagements-${group.key}`} className="text-lg text-ink">
            {group.title}
          </h2>
          <ul className="mt-2 border-b border-line">
            {group.items.map((item) => (
              <li key={item.id}>
                <EngagementRow item={item} mine={mine} href={`${basePath}/${encodeURIComponent(item.id)}${query}`} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
