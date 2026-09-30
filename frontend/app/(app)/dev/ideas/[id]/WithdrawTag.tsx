"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

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
 * withdrawn pitch no longer counts against the plan's cap. A native <dialog> asks first; it traps focus, closes on
 * Escape and returns focus to the button. A pitch that reached the organisation is withdrawn on its tracker instead.
 */
export function WithdrawTag({ proposalId, tagId, orgName, returnFocusTo, withdrawImpl = withdrawTag }: WithdrawTagProps) {
  const t = useStrings("tagWithdraw");
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const bodyId = useId();
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
          dialog.current?.showModal();
        }}
        aria-haspopup="dialog"
        aria-label={t("openLabel", { name: orgName })}
      >
        {t("open")}
      </Button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        // While the withdrawal is under way the dialog stays open: Escape and "Keep it" wait for the answer.
        onCancel={(event) => {
          if (busy) event.preventDefault();
        }}
        className={cn(
          "m-auto w-[calc(100%-2rem)] max-w-md rounded-panel border border-line bg-paper p-6 text-ink",
          "backdrop:bg-scrim",
        )}
      >
        <h2 id={titleId} className="text-lg text-ink">
          {t("title")}
        </h2>
        <p id={bodyId} className="mt-3 [overflow-wrap:anywhere] text-ink">
          {t("body", { name: orgName })}
        </p>
        {problem ? <Alert className="mt-4">{t(`problem.${problem}`)}</Alert> : null}
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" busy={busy} onClick={() => dialog.current?.close()} autoFocus>
            {t("cancel")}
          </Button>
          {/* Styled as the dialog's main button but not the screen's primary action (data-primary stays on the page's). */}
          <button type="button" onClick={confirm} aria-disabled={busy || undefined} className={buttonClass("primary")}>
            {busy ? t("busy") : t("confirm")}
          </button>
        </div>
      </dialog>
    </>
  );
}
