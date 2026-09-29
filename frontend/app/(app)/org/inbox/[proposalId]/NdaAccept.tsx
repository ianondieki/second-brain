"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { api } from "@/lib/api/client";

import { ACTION_HREF, REFUSAL_ACTION, refusalOf, type Refusal, type RefusalAction } from "../../refusals";

/** The page's words for this form, formatted on the server (no i18n runtime in the browser). */
export interface NdaAcceptStrings {
  accept: string;
  accepting: string;
  refusal: Record<Refusal, string>;
  action: Record<Exclude<RefusalAction, null>, string>;
}

export interface NdaAcceptProps {
  orgId: string;
  proposalId: string;
  /** Exactly what was shown: the API refuses a newer version or notice (409 nda_outdated) instead of accepting it unseen. */
  templateId: string;
  sha256: string;
  noticeVersion: string;
  /** Where the marked full proposal opens once accepted. */
  viewHref: string;
  inboxHref: string;
  strings: NdaAcceptStrings;
}

/**
 * "Accept and view", the step's one primary action (REQ-REPO-01): POST …/nda with the template id, its SHA-256 and the
 * logging-notice version that were shown, then open the marked page. A refusal is one sentence and at most one action;
 * "Show the new version", "Confirm" and "Try again" fetch the page again, which shows the step it now needs.
 */
export function NdaAccept({
  orgId,
  proposalId,
  templateId,
  sha256,
  noticeVersion,
  viewHref,
  inboxHref,
  strings,
}: NdaAcceptProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const notice = useRef<HTMLDivElement>(null);

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setRefusal(null);
    let refused: Refusal;
    try {
      const { response, error } = await api.POST("/api/orgs/{org_id}/proposals/{proposal_id}/nda", {
        params: { path: { org_id: orgId, proposal_id: proposalId } },
        body: { template_id: templateId, sha256, logging_notice_version: noticeVersion },
      });
      if (response.ok) {
        router.replace(viewHref); // stays busy until the marked page replaces this step
        return;
      }
      refused = refusalOf(response.status, error);
    } catch {
      refused = "generic"; // offline or reset: the same "try again" as a failing server
    }
    setBusy(false);
    setRefusal(refused);
    requestAnimationFrame(() => notice.current?.focus());
  }

  const action = refusal ? REFUSAL_ACTION[refusal] : null;
  const href = action === "inbox" ? inboxHref : action ? ACTION_HREF[action] : undefined;
  return (
    <Form onSubmit={accept} className="flex flex-col items-start gap-4" aria-busy={busy || undefined}>
      {refusal ? (
        <Alert ref={notice} className="w-full" tone="error">
          <p data-refusal={refusal}>{strings.refusal[refusal]}</p>
          {action && href ? (
            <Link href={href} className={standaloneLinkClass}>
              {strings.action[action]}
            </Link>
          ) : action ? (
            <Button
              variant="link"
              onClick={() => {
                setRefusal(null);
                router.refresh();
              }}
            >
              {strings.action[action]}
            </Button>
          ) : null}
        </Alert>
      ) : null}
      <SubmitButton variant="primary" busy={busy}>
        {busy ? strings.accepting : strings.accept}
      </SubmitButton>
    </Form>
  );
}
