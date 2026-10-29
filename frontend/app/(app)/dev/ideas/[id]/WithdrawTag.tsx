"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { withdrawTag } from "./pitch/calls";
import type { WithdrawProblem } from "./pitch/refusals";

const STALE: ReadonlySet<WithdrawProblem> = new Set(["closed", "delivered", "notFound"]);

export interface WithdrawTagProps {
  proposalId: string;
  tagId: string;
  orgName: string;
  /** The id of the pitches heading, which takes focus once the list shows the withdrawn pitch. */
  returnFocusTo: string;
  withdrawImpl?: typeof withdrawTag;
}

/**
 * Withdraw a pitch that is saved until the organisation verifies (REQ-DIR-04): the organisation never saw it, and a
 * withdrawn pitch no longer counts against the plan's cap. A ConfirmDialog asks first; it traps focus, closes on
 * Escape and returns focus to the button. A pitch that reached the organisation is withdrawn on its tracker instead.
 */
export function WithdrawTag({ proposalId, tagId, orgName, returnFocusTo, withdrawImpl = withdrawTag }: WithdrawTagProps) {
  const t = useStrings("tagWithdraw");
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<WithdrawProblem | null>(null);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const outcome = await withdrawImpl(proposalId, tagId);
    setBusy(false);
    if (!outcome.ok) {
      setProblem(outcome.problem);
      // The pitch changed elsewhere (closed, delivered or gone): the list behind the dialog catches up.
      if (STALE.has(outcome.problem)) router.refresh();
      return;
    }
    dialog.current?.close();
    router.refresh();
    document.getElementById(returnFocusTo)?.focus();
  }

  return (
    <>
      <Button
        variant="secondary"
        className="self-start"
        onClick={() => {
          setProblem(null);
          openConfirm(dialog.current);
        }}
        aria-haspopup="dialog"
        aria-label={t("openLabel", { name: orgName })}
      >
        {t("open")}
      </Button>
      {/* While the withdrawal is under way the dialog stays open: Escape and "Keep it" wait for the answer. */}
      <ConfirmDialog
        ref={dialog}
        tone="danger"
        title={t("title")}
        confirmLabel={t("confirm")}
        busyLabel={t("busy")}
        cancelLabel={t("cancel")}
        busy={busy}
        onConfirm={() => void confirm()}
        problem={problem ? <Alert>{t(`problem.${problem}`)}</Alert> : null}
      >
        <p>{t("body", { name: orgName })}</p>
      </ConfirmDialog>
    </>
  );
}
