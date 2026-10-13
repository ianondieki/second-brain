"use client";

import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import { teamCalls, type TeamCalls } from "./calls";
import { useTeamWrite } from "./useTeamWrite";

/**
 * An open invitation's two quiet actions (REQ-TEN-02): Resend (a new 7-day link, the earlier one stops working; the
 * invitation gets a new id, so the list is read again) and Revoke (its link stops working at once). Neither needs a
 * confirmation: inviting again undoes a revoke. Resending may ask for a fresh second factor first.
 */
export function InvitationActions({
  orgId,
  invitationId,
  email,
  enrolled,
  calls,
}: {
  orgId: string;
  invitationId: string;
  email: string;
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const api = calls ?? teamCalls(orgId);
  const write = useTeamWrite({ enrolled });
  const [doing, setDoing] = useState<"resend" | "revoke" | null>(null);
  const [resent, setResent] = useState(false);
  const done = useRef<HTMLDivElement>(null);

  function act(kind: "resend" | "revoke") {
    if (write.busy) return;
    setDoing(kind);
    setResent(false);
    void write.run(
      () => (kind === "resend" ? api.resend(invitationId) : api.revoke(invitationId)),
      () => {
        if (kind === "resend") {
          setResent(true);
          requestAnimationFrame(() => done.current?.focus());
        }
      },
    );
  }

  if (write.stepUp) return <div className="mt-1 w-full sm:col-span-2">{write.stepUp}</div>;

  return (
    <div
      className="flex w-full flex-col gap-3 sm:col-start-2 sm:row-start-1 sm:w-auto sm:items-end"
      data-invitation-actions={invitationId}
    >
      <div className="flex gap-2">
        <Button
          variant="link"
          busy={write.busy}
          onClick={() => act("resend")}
          aria-label={write.busy && doing === "resend" ? undefined : t("resendLabel", { email })}
          data-resend=""
        >
          {write.busy && doing === "resend" ? t("resending") : t("resend")}
        </Button>
        <Button
          variant="link"
          busy={write.busy}
          onClick={() => act("revoke")}
          aria-label={write.busy && doing === "revoke" ? undefined : t("revokeLabel", { email })}
          data-revoke=""
        >
          {write.busy && doing === "revoke" ? t("revoking") : t("revoke")}
        </Button>
      </div>
      {resent ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p>{t("resent", { email })}</p>
        </Alert>
      ) : null}
      {write.problem}
    </div>
  );
}
