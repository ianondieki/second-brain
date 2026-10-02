"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import type { Refused } from "../../brief-draft";
import { briefCalls, type BriefCalls } from "../calls";

/**
 * "Close this brief" (REQ-DIR-05): a secondary button, then a confirmation (a bottom sheet on phones, D-52) that says
 * what closing does before anything does. Closed, the page reads again; a Brief someone closed meanwhile (409) reads
 * again too, since it is already what was asked. Any other refusal stays in the dialog in words.
 */
export function CloseBrief({
  orgId,
  briefId,
  orgName,
  calls = briefCalls,
}: {
  orgId: string;
  briefId: string;
  orgName: string;
  calls?: BriefCalls;
}) {
  const t = useStrings("briefForm");
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<Refused | null>(null);

  async function close() {
    if (busy) return;
    setBusy(true);
    setRefused(null);
    const outcome = await calls.close(orgId, briefId);
    setBusy(false);
    if (outcome.ok || outcome.refusal === "closed") {
      dialog.current?.close();
      router.refresh();
      return;
    }
    setRefused(outcome);
  }

  return (
    <>
      <Button variant="secondary" onClick={() => openConfirm(dialog.current)} data-close-brief="">
        {t("close.open")}
      </Button>
      <ConfirmDialog
        ref={dialog}
        title={t("close.title")}
        confirmLabel={t("close.confirm")}
        busyLabel={t("close.closing")}
        cancelLabel={t("close.cancel")}
        busy={busy}
        tone="danger"
        onConfirm={() => void close()}
        onClose={() => setRefused(null)}
        problem={
          refused ? (
            <Alert>
              <p data-refusal={refused.refusal}>{t(`refusal.${refused.refusal}`, { org: orgName, limit: 0 })}</p>
            </Alert>
          ) : null
        }
      >
        <p>{t("close.body")}</p>
      </ConfirmDialog>
    </>
  );
}
