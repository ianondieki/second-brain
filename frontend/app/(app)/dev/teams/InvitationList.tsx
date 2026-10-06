"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";

import { teamCalls, type TeamCalls } from "./calls";
import { threadHref, type Invitation, type Invitations } from "./teams";

type Step = "accept" | "decline" | "withdraw";
type Said = { kind: "accepted"; name: string; threadId: string } | { kind: "declined" | "withdrawn" | "gone" | "failed" };

/**
 * The pending invitations of /dev/teams (REQ-DEV-03): the ones received first (who, the problem, their note, then
 * Accept and Decline), then the ones sent (Withdraw). Each answer leaves the list and a status line says what
 * happened (it takes focus); after Accept it links the new thread. The page is not read again (that would take the
 * section, and its status line, away with the last card). No button here is the screen's primary action.
 */
export function InvitationList({ initial, calls: given }: { initial: Invitations; calls?: Partial<TeamCalls> }) {
  const t = useStrings("teamUp");
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(), ...given }));
  const [answered, setAnswered] = useState<Record<string, true>>({});
  const [busy, setBusy] = useState<{ id: string; step: Step } | null>(null);
  const [said, setSaid] = useState<(Said & { n: number }) | null>(null);
  const status = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  function say(next: Said) {
    setSaid((now) => ({ ...next, n: (now?.n ?? 0) + 1 }));
  }

  async function answer(invitation: Invitation, step: Step) {
    if (busy) return;
    setBusy({ id: invitation.id, step });
    const outcome = step === "accept" ? await calls.accept(invitation.id) : await calls[step](invitation.id);
    setBusy(null);
    if (outcome.ok || outcome.refusal === "gone") setAnswered((now) => ({ ...now, [invitation.id]: true }));
    if (!outcome.ok) say({ kind: outcome.refusal });
    else if (step === "accept" && "threadId" in outcome) {
      say({ kind: "accepted", name: invitation.counterpart?.handle ?? t("invitation.someone"), threadId: String(outcome.threadId) });
    } else say({ kind: step === "withdraw" ? "withdrawn" : "declined" });
  }

  const received = initial.received.filter((item) => !answered[item.id]);
  const sent = initial.sent.filter((item) => !answered[item.id]);

  return (
    <div className="flex flex-col gap-6">
      {said ? (
        <Alert key={said.n} ref={status} tone={said.kind === "failed" || said.kind === "gone" ? "error" : "ok"}>
          {said.kind === "accepted" ? (
            <span className="flex flex-col items-start">
              {t("invitation.accepted", { name: said.name })}
              <Link href={threadHref(said.threadId)} className={standaloneLinkClass} data-open-thread="">
                {t("invitation.openThread")}
              </Link>
            </span>
          ) : (
            t(`invitation.${said.kind}`)
          )}
        </Alert>
      ) : null}

      {received.length > 0 ? (
        <ul aria-label={t("invitation.receivedLabel")} className="grid grid-cols-1 gap-4 sm:grid-cols-2" data-invitations="received">
          {received.map((item) => (
            <li key={item.id} className="min-w-0">
              <InvitationCard item={item} raised>
                <Button busy={busy?.id === item.id && busy.step === "accept"} aria-describedby={`invitation-${item.id}`} onClick={() => void answer(item, "accept")} data-accept="">
                  {busy?.id === item.id && busy.step === "accept" ? t("invitation.accepting") : t("invitation.accept")}
                </Button>
                <Button variant="danger" busy={busy?.id === item.id && busy.step === "decline"} aria-describedby={`invitation-${item.id}`} onClick={() => void answer(item, "decline")} data-decline="">
                  {busy?.id === item.id && busy.step === "decline" ? t("invitation.declining") : t("invitation.decline")}
                </Button>
              </InvitationCard>
            </li>
          ))}
        </ul>
      ) : null}

      {sent.length > 0 ? (
        <ul aria-label={t("invitation.sentLabel")} className="grid grid-cols-1 gap-4 sm:grid-cols-2" data-invitations="sent">
          {sent.map((item) => (
            <li key={item.id} className="min-w-0">
              <InvitationCard item={item}>
                <Button variant="danger" busy={busy?.id === item.id} aria-describedby={`invitation-${item.id}`} onClick={() => void answer(item, "withdraw")} data-withdraw="">
                  {busy?.id === item.id ? t("invitation.withdrawing") : t("invitation.withdraw")}
                </Button>
              </InvitationCard>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** One invitation: who and which problem, the note as typed (plain text), then its buttons. */
function InvitationCard({ item, raised = false, children }: { item: Invitation; raised?: boolean; children: ReactNode }) {
  const t = useStrings("teamUp");
  const name = item.counterpart?.handle ?? t("invitation.someone");
  return (
    <article
      aria-labelledby={`invitation-${item.id}`}
      data-invitation={item.id}
      className={`flex h-full flex-col rounded-panel border border-line bg-field p-4 sm:p-5 ${raised ? "shadow-card" : ""}`}
    >
      <h3 id={`invitation-${item.id}`} className="font-semibold text-ink [overflow-wrap:anywhere]">
        {item.direction === "received" ? t("invitation.received", { name }) : t("invitation.sent", { name })}
      </h3>
      <p className="mt-1 text-sm text-ink-soft [overflow-wrap:anywhere]">
        {item.problem.title ? t("invitation.on", { title: item.problem.title }) : t("invitation.problemGone")}
      </p>
      {item.note ? (
        <p className="mt-3 rounded-control bg-paper px-3 py-2 whitespace-pre-wrap text-ink [overflow-wrap:anywhere]" data-note="">
          {item.note}
        </p>
      ) : null}
      <div className="mt-auto flex flex-wrap gap-3 pt-4">{children}</div>
    </article>
  );
}
