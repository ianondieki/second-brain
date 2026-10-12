import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { PartButton } from "@/components/tracker/lazy";
import { isFinished, type TrackerDetail } from "@/components/tracker/model";
import { Avatar } from "@/components/ui/Avatar";
import { buttonClass } from "@/components/ui/Button";
import { formatCalendarDate } from "@/lib/format";

// The organisation's own lines on its tracker (P27): its team triage under the whose-turn banner (REQ-ENG-15; D-68)
// and its prior-knowledge declaration under its buttons (REQ-PROV-06; docs/spec/06 6.4 pt 5). Server-rendered: only
// the openers are client code, and the sheets they open load when pressed (components/tracker/lazy.tsx). Nothing
// here is ever drawn for a developer: EngagementScreen mounts these for `my_party === "org"` only, and each checks
// again (a developer's tracker carries no `team` in the API either; a test hands one in and expects nothing).

/** The roles that may assign and recommend (engagements/models.py TRIAGE_ROLES). */
const TRIAGE_ROLES = new Set(["owner", "admin", "reviewer", "signatory"]);

/** Links styled as quiet text buttons, 44 px tall (the openers of the sheets). */
const OPENER =
  "inline-flex min-h-11 items-center font-semibold text-accent underline decoration-1 underline-offset-4 hover:decoration-2";

export function canTriage(detail: Pick<TrackerDetail, "my_roles">): boolean {
  return detail.my_roles.some((role) => TRIAGE_ROLES.has(role));
}

/** "Assigned to Wanjiru · Change" and "Recommended: pursue 2 · pass 0 · discuss 1 · See recommendations". */
export async function TeamPanel({ detail, myUserId }: { detail: TrackerDetail; myUserId: string }) {
  if (detail.my_party !== "org" || !detail.team) return null;
  const t = await getTranslations("tracker.team");
  const locale = await getLocale();
  const team = detail.team;
  const triage = canTriage(detail);
  const counts = team.recommendations;
  const total = counts.pursue + counts.pass + counts.discuss;
  const assignee = team.assignee;
  const mine = assignee?.user_id === myUserId;
  const sheet = { orgId: detail.org_id, engagementId: detail.id, canTriage: triage, myUserId, locale };
  const figure = (chunks: ReactNode) => (
    <span className="font-figure font-semibold text-ink tabular-nums">{chunks}</span>
  );
  return (
    <section
      aria-label={t("label")}
      data-team-panel=""
      className="flex flex-col gap-1 border-t border-line px-5 py-2 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-7"
    >
      <p className="flex min-w-0 flex-wrap items-center gap-x-3" data-assignee={assignee?.user_id ?? ""}>
        {assignee ? <Avatar name={assignee.display_name} size="sm" active={mine} /> : null}
        <span className={assignee ? "[overflow-wrap:anywhere] text-ink" : "text-ink-soft"}>
          {assignee ? (mine ? t("assignedToYou") : t("assignedTo", { name: assignee.display_name })) : t("unassigned")}
        </span>
        {triage ? (
          <PartButton
            part="team"
            props={{ ...sheet, focus: "assign" }}
            label={assignee ? t("change") : t("assign")}
            className={OPENER}
          />
        ) : null}
      </p>
      <p
        className="flex min-w-0 flex-wrap items-center gap-x-3"
        data-tally={`${counts.pursue}-${counts.pass}-${counts.discuss}`}
      >
        <span className="text-ink-soft">
          {total > 0
            ? t.rich("tally", { pursue: counts.pursue, pass: counts.pass, discuss: counts.discuss, f: figure })
            : t("none")}
        </span>
        {total > 0 || triage ? (
          <PartButton
            part="team"
            props={{ ...sheet, focus: "recommendations" }}
            label={total > 0 ? t("see") : t("recommend")}
            className={OPENER}
          />
        ) : null}
      </p>
    </section>
  );
}

/** The Nairobi calendar day of an instant ("2026-10-02"). */
function nairobiDay(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date(iso));
}

/**
 * The declaration's line under the organisation's buttons: when its window opens, until when it may declare (with
 * "Declare prior knowledge" for an owner, admin or signatory while it may), that it declared, or that the window
 * closed. Nothing on an engagement that ended without a declaration.
 */
export async function DeclarationLine({ detail }: { detail: TrackerDetail }) {
  if (detail.my_party !== "org" || !detail.prior_knowledge) return null;
  const pk = detail.prior_knowledge;
  if (!pk.declared_at && isFinished(detail.state)) return null;
  const t = await getTranslations("tracker.declaration");
  const locale = await getLocale();
  const closes = pk.window_closes_on ? formatCalendarDate(locale, pk.window_closes_on) : null;
  const today = detail.today ?? nairobiDay(new Date().toISOString());
  let sentence: string;
  let state: string;
  if (pk.declared_at) {
    sentence = t("declared", { date: formatCalendarDate(locale, nairobiDay(pk.declared_at)) });
    state = "declared";
  } else if (!pk.first_tier2_view_at || !pk.window_closes_on || !closes) {
    sentence = t("notYet");
    state = "notYet";
  } else if (pk.can_declare || pk.window_closes_on >= today) {
    sentence = pk.can_declare ? t("open", { date: closes }) : t("openOthers", { date: closes });
    state = "open";
  } else {
    sentence = t("closed", { date: closes });
    state = "closed";
  }
  return (
    <section
      aria-label={t("label")}
      data-declaration={state}
      className="flex flex-col items-start gap-2 border-t border-line px-5 py-3 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-7"
    >
      <p id="prior-knowledge" tabIndex={-1} className="max-w-[60ch] text-ink-soft focus-visible:outline-none">
        {sentence}
      </p>
      {pk.can_declare && pk.first_tier2_view_at && pk.window_closes_on ? (
        <PartButton
          part="declaration"
          props={{
            orgId: detail.org_id,
            engagementId: detail.id,
            closesOn: pk.window_closes_on,
            firstViewOn: nairobiDay(pk.first_tier2_view_at),
            locale,
          }}
          after="prior-knowledge"
          label={t("declare")}
          className={buttonClass("secondary", "w-full shrink-0 sm:w-auto")}
        />
      ) : null}
    </section>
  );
}
