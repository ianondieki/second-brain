import { getLocale, getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";

import { formatMoment } from "../dates";
import type { ProposalViews } from "./pitch/picker";

/**
 * "Who has seen this" (REQ-PROV-03, REQ-REPO-03): every opening of the idea's full details, newest first, with the
 * person, their organisation, the time in Nairobi, the version and the NDA version they accepted. Views are recorded
 * only after the viewer accepted the NDA, which the note says in the approved phrasing (docs/spec/04 4.2). The owner's
 * own preview is not a view. Empty: one sentence and one action.
 */
export async function WhoHasSeen({ views }: { views: ProposalViews | null }) {
  const t = await getTranslations("ideaViews");
  const locale = await getLocale();
  return (
    <section aria-labelledby="views-heading" className="mt-10">
      <h2 id="views-heading" className="text-lg text-ink">
        {t("title")}
      </h2>
      <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{t("note")}</p>
      {!views ? (
        <p className="mt-4 text-ink">{t("loadFailed")}</p>
      ) : views.items.length === 0 ? (
        <EmptyState className="mt-4" sentence={t("empty")} action={t("emptyAction")} href="/dev/companies" />
      ) : (
        <ol aria-label={t("listLabel")} className="mt-4 border-b border-line">
          {views.items.map((view) => (
            <li key={view.view_id} data-view={view.view_id} className="flex flex-col gap-0.5 border-t border-line py-3">
              <p className="font-semibold [overflow-wrap:anywhere] text-ink">
                {t("viewer", { name: view.viewer_name, org: view.org.name ?? t("unknownOrg") })}
              </p>
              <p className="text-sm text-ink">
                <time dateTime={view.viewed_at}>{t("when", { time: formatMoment(locale, view.viewed_at) })}</time>
              </p>
              <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
                <span>{t("version", { number: view.version_no })}</span>
                {view.nda_version ? <span>{t("nda", { version: view.nda_version })}</span> : null}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
