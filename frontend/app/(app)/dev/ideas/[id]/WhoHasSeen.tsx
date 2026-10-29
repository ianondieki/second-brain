import { getLocale, getTranslations } from "next-intl/server";

import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";

import { formatMoment } from "../dates";

import type { ProposalViews } from "./pitch/picker";

/**
 * "Who has seen this" (REQ-PROV-03, REQ-REPO-03): every opening of the idea's full details, newest first, as a row
 * of a list with the viewer's avatar (D-52; P20: a list is rows): the person and their organisation, the time in Nairobi, the version and the NDA
 * version they accepted. Views are recorded only after the viewer accepted the NDA, which the note says in the
 * approved phrasing (docs/spec/04 4.2). The owner's own preview is not a view. Empty: one sentence and one action.
 */
export async function WhoHasSeen({ views }: { views: ProposalViews | null }) {
  const t = await getTranslations("ideaViews");
  const locale = await getLocale();
  return (
    <Section title={t("title")} headingId="views-heading" description={t("note")}>
      {!views ? (
        <p className="text-ink">{t("loadFailed")}</p>
      ) : views.items.length === 0 ? (
        <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/dev/companies" />
      ) : (
        <ol aria-label={t("listLabel")} className="flex flex-col border-b border-line">
          {views.items.map((view) => (
            <li key={view.view_id}>
              <article data-view={view.view_id} className="flex gap-4 border-t border-line py-4">
                <Avatar name={view.viewer_name} kind="person" />
                <div className="min-w-0">
                  <h3 className="text-base [overflow-wrap:anywhere] text-ink">
                    {t("viewer", { name: view.viewer_name, org: view.org.name ?? t("unknownOrg") })}
                  </h3>
                  <p className="mt-0.5 text-sm text-ink-soft">
                    <time dateTime={view.viewed_at}>{t("when", { time: formatMoment(locale, view.viewed_at) })}</time>
                  </p>
                  <p className="mt-1.5 flex flex-wrap gap-x-4 text-sm text-ink-soft">
                    <span>{t("version", { number: view.version_no })}</span>
                    {view.nda_version ? <span>{t("nda", { version: view.nda_version })}</span> : null}
                  </p>
                </div>
              </article>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
