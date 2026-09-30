import { getLocale, getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import { formatMoment } from "../dates";
import type { ProposalViews } from "./pitch/picker";

/**
 * "Who has seen this" (REQ-PROV-03, REQ-REPO-03): every opening of the idea's full details, newest first, with the
 * person, their organisation, the time in Nairobi, the version and the NDA version they accepted. Views are recorded
 * only after the viewer accepted the NDA, which the note says in the approved phrasing (docs/spec/04 4.2). The owner's
 * own preview is not a view. Empty: one sentence and one action. A Section with an ordered RowList.
 */
export async function WhoHasSeen({ views }: { views: ProposalViews | null }) {
  const t = await getTranslations("ideaViews");
  const locale = await getLocale();
  return (
    <Section title={t("title")} headingId="views-heading" description={t("note")} className="mt-12">
      {!views ? (
        <p className="text-ink">{t("loadFailed")}</p>
      ) : views.items.length === 0 ? (
        <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/dev/companies" />
      ) : (
        <RowList ordered aria-label={t("listLabel")}>
          {views.items.map((view) => (
            <Row
              key={view.view_id}
              data-view={view.view_id}
              title={t("viewer", { name: view.viewer_name, org: view.org.name ?? t("unknownOrg") })}
              meta={<time dateTime={view.viewed_at}>{t("when", { time: formatMoment(locale, view.viewed_at) })}</time>}
            >
              <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
                <span>{t("version", { number: view.version_no })}</span>
                {view.nda_version ? <span>{t("nda", { version: view.nda_version })}</span> : null}
              </p>
            </Row>
          ))}
        </RowList>
      )}
    </Section>
  );
}
