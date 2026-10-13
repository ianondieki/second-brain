"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";
import { loginHref } from "@/lib/return-path";

type Refusal = "mismatch" | "gone" | "member" | "seats" | "locked" | "signedOut" | "rateLimited" | "network" | "generic";

/** Refusals that another press cannot change: the button goes. */
const FINAL: ReadonlySet<Refusal> = new Set(["mismatch", "gone", "member", "seats", "locked"]);

/** Why accepting did not happen, from the answer's status and code (never the server's words). */
export function acceptRefusal(status: number, error: unknown): Refusal {
  const code = apiErrorCode(error);
  if (code === "invitation_email_mismatch") return "mismatch";
  if (code === "already_member") return "member";
  if (code === "public_demo_locked") return "locked";
  if (code === "plan_limit" || status === 402) return "seats";
  if (status === 429) return "rateLimited";
  if (status === 404) return "gone";
  if (status === 401) return "signedOut";
  return "generic";
}

/**
 * "Accept and join" for a signed-in visitor (POST /api/invitations/{token}/accept): the organisation's portal opens
 * (with ?org=, for someone who now belongs to several). Refused, one sentence says why: another address than the
 * invitation's (and nothing about which), a link that no longer works, already a member (with the way in), no free
 * seat on the organisation's plan (402 plan_limit: the invitee does not pay, so they ask the inviter), too many tries,
 * or the session ended (with the way back through sign-in to this page).
 */
export function AcceptInvitation({
  token,
  orgName,
  client = api,
}: {
  token: string;
  orgName: string;
  client?: ApiClient;
}) {
  const t = useStrings("invitationAccept");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const notice = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (refusal) notice.current?.focus();
  }, [refusal]);

  async function accept() {
    if (busy) return;
    setBusy(true);
    setRefusal(null);
    try {
      const { data, error, response } = await client.POST("/api/invitations/{token}/accept", {
        params: { path: { token } },
      });
      if (data) {
        router.push(`/org?org=${encodeURIComponent(data.org_id)}`);
        return;
      }
      setRefusal(acceptRefusal(response.status, error));
    } catch {
      setRefusal("network");
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-col items-stretch gap-4 sm:items-start">
      {refusal ? (
        <Alert ref={notice} className="w-full">
          <p data-refusal={refusal}>{t(`refusal.${refusal}`, { org: orgName })}</p>
          {refusal === "member" ? (
            <a href="/org" className={standaloneLinkClass}>
              {t("openOrg")}
            </a>
          ) : refusal === "signedOut" ? (
            <a href={loginHref(`/invitations/${token}`)} className={standaloneLinkClass}>
              {t("signIn")}
            </a>
          ) : null}
        </Alert>
      ) : null}
      {refusal && FINAL.has(refusal) ? null : (
        <Button variant="primary" busy={busy} onClick={() => void accept()} data-accept="">
          {busy ? t("accepting") : t("accept")}
        </Button>
      )}
    </div>
  );
}
