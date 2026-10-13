"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";
import { endSession } from "@/lib/auth/sign-out";
import { retryAfterSeconds, retryWhen } from "@/lib/retry-after";


type Refusal =
  | "mismatch"
  | "gone"
  | "member"
  | "developer"
  | "seats"
  | "locked"
  | "signedOut"
  | "rateLimited"
  | "conflict"
  | "network"
  | "generic";

function retryLine(
  tr: (key: "minute" | "minutes" | "hour" | "hours" | "later", values?: Record<string, number>) => string,
  seconds: number | null,
): string {
  const when = retryWhen(seconds);
  return tr(when.key, when.count === undefined ? undefined : { count: when.count });
}

/** Refusals that another press cannot change: the button goes. */
const FINAL: ReadonlySet<Refusal> = new Set(["mismatch", "gone", "member", "developer", "seats", "locked"]);

/** Why accepting did not happen, from the answer's status and code (never the server's words). */
export function acceptRefusal(status: number, error: unknown): Refusal {
  const code = apiErrorCode(error);
  if (code === "invitation_email_mismatch") return "mismatch";
  if (code === "already_member") return "member";
  if (code === "developer_account") return "developer";
  if (code === "conflict") return "conflict";
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
  signInHref,
  client = api,
}: {
  token: string;
  orgName: string;
  /** Sign in again, back here (built on the server: the sign-in screens keep lib/return-path to themselves). */
  signInHref: string;
  client?: ApiClient;
}) {
  const t = useStrings("invitationAccept");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const tr = useStrings("retryAfter");
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [switchFailed, setSwitchFailed] = useState(false);
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
      setRetryAfter(retryAfterSeconds(response.headers.get("Retry-After")));
      setRefusal(acceptRefusal(response.status, error));
    } catch {
      setRefusal("network");
    }
    setBusy(false);
  }

  async function switchAccount() {
    if (busy) return;
    setBusy(true);
    setSwitchFailed(false);
    // The app's one sign-out (offline copies, the session, the remembered address and recent pages).
    if (await endSession()) {
      // A full load after signing out, as the account menu's fallback sign-out does: nothing of the old session stays.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/invitations/${token}`);
      return;
    }
    // Not signed out (refused or offline): stay here and say so.
    setBusy(false);
    setSwitchFailed(true);
  }

  return (
    <div className="flex flex-col items-stretch gap-4 sm:items-start">
      {refusal ? (
        <Alert ref={notice} className="w-full">
          <p data-refusal={refusal}>{t(`refusal.${refusal}`, { org: orgName })}</p>
          {refusal === "rateLimited" ? <p>{retryLine(tr, retryAfter)}</p> : null}
          {refusal === "conflict" ? (
            <a href={`/invitations/${token}`} className={standaloneLinkClass}>
              {t("reload")}
            </a>
          ) : refusal === "member" ? (
            <a href="/org" className={standaloneLinkClass}>
              {t("openOrg")}
            </a>
          ) : refusal === "mismatch" ? (
            // Another address than the invitation's: sign out, then this page again (signed out, its sign-in and
            // sign-up offers), so the right account can accept.
            <>
              {/* Left-aligned like the alert's other links (a block-level box as wide as its words). */}
              <Button
                variant="link"
                busy={busy}
                onClick={() => void switchAccount()}
                className="flex w-fit justify-start text-left"
                data-switch-account=""
              >
                {busy ? t("signingOut") : t("switchAccount")}
              </Button>
              {switchFailed ? <p data-sign-out-failed="">{t("signOutFailed")}</p> : null}
            </>
          ) : refusal === "signedOut" ? (
            <a href={signInHref} className={standaloneLinkClass}>
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
