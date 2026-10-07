import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Section } from "@/components/ui/Section";
import { clientStrings } from "@/lib/i18n/client-strings";

import { tier2ShareState } from "./data";
import { eatParts, isFinished, type Detail } from "./model";
import { SHARE_ORIGINS } from "./share";
import { LazyShareTier2 } from "./lazy";

/**
 * The full proposal on an engagement an organisation opened (REQ-ENG-04; docs/spec/06 6.9 stage 0, "Tier 2 by manual
 * grant"). The developer shares it by hand (ShareTier2, never the screen's primary action: the disclosure cannot be taken
 * back), or sees when they did; the organisation, once it is shared,
 * gets the way to open it, under the Evaluation NDA on the proposal's page. Nothing for a pitched engagement (its
 * disclosure policy applies) or before the developer shares.
 */
export async function Tier2Section({
  detail,
  enrolled,
  query,
}: {
  detail: Detail;
  enrolled: boolean;
  /** "?org=<id>" for a member of several organisations. */
  query: string;
}) {
  if (!SHARE_ORIGINS.has(detail.origin)) return null;
  const share = await tier2ShareState(detail.id);
  if (!share) return null;
  const t = await getTranslations("tier2Share");
  const locale = await getLocale();
  const when = share.shared_at ? eatParts(share.shared_at, locale).date : "";

  if (detail.my_party === "org") {
    if (!share.shared) return null;
    return (
      <Section title={t("title")} headingId="share-heading" data-tier2-share="shared">
        <div className="flex flex-col items-start gap-2">
          <p className="max-w-[60ch] text-ink">{t("orgShared", { org: detail.org_name, date: when })}</p>
          <Link
            href={`/org/inbox/${encodeURIComponent(detail.proposal_id)}${query}`}
            className={standaloneLinkClass}
            data-open-full=""
          >
            {t("open")}
          </Link>
        </div>
      </Section>
    );
  }

  if (share.shared) {
    return (
      <Section title={t("title")} headingId="share-heading" data-tier2-share="shared">
        {/* ShareTier2 moves focus here once the refreshed page shows the share (a stable id). */}
        <p id="share-status" tabIndex={-1} className="max-w-[60ch] text-ink focus:outline-none">
          {t("shared", { org: detail.org_name, date: when })}
        </p>
      </Section>
    );
  }
  if (isFinished(detail.state)) return null;
  return (
    <ClientStrings strings={await clientStrings(["tier2Share"])}>
      <LazyShareTier2 engagementId={detail.id} orgName={detail.org_name} enrolled={enrolled} />
    </ClientStrings>
  );
}
