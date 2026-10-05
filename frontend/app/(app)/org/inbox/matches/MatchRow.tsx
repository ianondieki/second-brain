import { useLocale, useTranslations } from "next-intl";

import { Chip } from "@/components/tracker/Chip";
import { Row } from "@/components/ui/RowList";

import { formatDay } from "../../format";
import type { Membership } from "../../membership";
import type { Match } from "../../scout";
import { editsShortlist } from "../../shortlist";
import { ShortlistControl } from "../ShortlistControl";
import { FitMeter, Why } from "./MatchParts";

/**
 * One scout match in the Inbox (REQ-SCOUT-02): its fit, when the scout found it, the title (a link to the match page),
 * the developer's pseudonymous handle (never a name or an id: docs/spec/06 6.1), the niche and why it matches. A
 * match whose proposal was unpublished or held shows only that it is no longer available: no teaser, no why. With
 * `org`, an available match ends in its shortlist star (REQ-REPO-02), or the read-only mark.
 */
export function MatchRow({ match, href, org }: { match: Match; href: string; org?: Membership }) {
  const t = useTranslations("scoutMatches");
  const locale = useLocale();
  const available = match.available && match.teaser !== null;
  const title = available ? (match.teaser?.title ?? t("unavailableTitle")) : t("unavailableTitle");
  const shortlisted = match.shortlisted ?? false;
  const found = <time dateTime={match.created_at}>{t("found", { date: formatDay(locale, match.created_at) })}</time>;
  return (
    <Row
      data-match={match.id}
      data-available={available ? "true" : "false"}
      headingLevel={2}
      titleId={`title-${match.proposal_id}`}
      title={title}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {available && match.owner_handle ? <span>{t("by", { handle: match.owner_handle })}</span> : null}
          {available ? <span>{match.niche?.label ?? t("nicheNotGiven")}</span> : null}
          {found}
        </span>
      }
      badges={[
        available ? (
          <FitMeter key="fit" score={match.score} />
        ) : (
          <Chip key="gone" kind="ended">
            {t("unavailable")}
          </Chip>
        ),
      ]}
      figure={
        org && available && (shortlisted || editsShortlist(org)) ? (
          <ShortlistControl org={org} proposalId={match.proposal_id} shortlisted={shortlisted} describedBy={`title-${match.proposal_id}`} />
        ) : undefined
      }
    >
      {available ? (
        <div className="mt-1">
          <Why match={match} />
        </div>
      ) : (
        <p className="text-sm text-ink-soft">{t("unavailableNote")}</p>
      )}
    </Row>
  );
}
