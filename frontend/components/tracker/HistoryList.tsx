import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Section } from "@/components/ui/Section";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";

import type { Command, History } from "./model";
import { Eat } from "./When";

/** The event names the History tab words: every command, plus the genesis ("create"). */
const EVENT_KEYS = new Set<string>([
  "create",
  "accept_interest",
  "decline_interest",
  "start_review",
  "decline",
  "approve",
  "withdraw",
  "mark_contacted",
  "confirm_contact",
  "send_nda",
  "sign_nda",
  "propose_terms",
  "mark_final",
  "reopen_negotiation",
  "sign_agreement",
  "start_milestone",
  "submit_milestone",
  "accept_milestone",
  "request_changes",
  "deliver",
  "accept_delivery",
  "sign_certificate",
  "record_payment",
  "confirm_payment",
] satisfies Array<Command | "create">);

/**
 * The History tab (REQ-ENG-02; docs/spec/06 6.9 Persistence): the engagement's events in order, each with its time
 * in EAT, who acted in which role, and what happened. Both parties see the same list (AC-TRACK-3). The line above it
 * says whether the hash chain checked out when the API read it.
 */
export function HistoryList({ history }: { history: History }) {
  const t = useTranslations("tracker");
  const events = [...history.events].sort((a, b) => b.seq - a.seq);
  return (
    <Section
      title={t("history.title")}
      headingId="history-heading"
      description={
        <Badge
          data-chain={history.chain_verified ? "verified" : "unverified"}
          tone={history.chain_verified ? "ok" : "error"}
          icon={history.chain_verified ? <CheckIcon /> : <AlertIcon />}
        >
          {history.chain_verified ? t("history.chainOk") : t("history.chainBroken")}
        </Badge>
      }
    >
      <ol className="flex flex-col">
        {events.map((event) => (
          <li key={event.id} data-event={event.command} className="border-t border-line py-3">
            <p className="font-semibold text-ink">
              {EVENT_KEYS.has(event.command) ? t(`event.${event.command as Command | "create"}`) : t("event.other")}
            </p>
            <p className="mt-0.5 text-sm text-ink">
              {t("history.actor", {
                name: event.actor_name ?? t("endorsements.platform"),
                role: t(`role.${event.actor_role}`),
              })}
            </p>
            <p className="mt-0.5 text-sm text-ink-soft">
              <Eat iso={event.created_at} />
            </p>
          </li>
        ))}
      </ol>
    </Section>
  );
}
