"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import { removeIdea } from "../calls";
import { BASE_PATH } from "../ideas";

// The dialog's confirm button, filled in the error colour (the trigger is Button's danger variant).
const DANGER_SOLID =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-control border px-5 text-base font-semibold " +
  "transition-colors duration-150 ease-out aria-disabled:cursor-progress " +
  "border-error bg-error text-on-accent hover:bg-[color-mix(in_oklab,var(--error)_84%,var(--ink))]";

export interface DeleteIdeaProps {
  id: string;
  /** Registered at least once: deleting hides it and keeps the evidence (REQ-PROV-05); a draft is removed. */
  registered: boolean;
  removeImpl?: typeof removeIdea;
}

/**
 * "Delete idea" with a confirmation dialog that says what happens before anything does (docs/spec/06 6.4, AC-IP-6):
 * a published idea is hidden and its registered versions, certificates and /verify records are kept; a draft that was
 * never published is removed. A native <dialog>: it traps focus, closes on Escape and returns focus to the button.
 */
export function DeleteIdea({ id, registered, removeImpl = removeIdea }: DeleteIdeaProps) {
  const t = useStrings("ideaDelete");
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<"failed" | "network" | null>(null);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const outcome = await removeImpl(id);
    if (outcome.ok) {
      router.push(`${BASE_PATH}?removed=${outcome.value.status === "hidden" ? "hidden" : "deleted"}`);
      return;
    }
    setBusy(false);
    setProblem(outcome.problem === "network" ? "network" : "failed");
  }

  return (
    <>
      <Button variant="danger" onClick={() => dialog.current?.showModal()} aria-haspopup="dialog">
        {t("open")}
      </Button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onClose={() => setProblem(null)}
        className={cn(
          "m-auto w-[calc(100%-2rem)] max-w-md rounded-panel border border-line bg-paper p-6 text-ink",
          "backdrop:bg-scrim",
        )}
      >
        <h2 id={titleId} className="text-lg text-ink">
          {t("title")}
        </h2>
        <p id={bodyId} className="mt-3 text-ink">
          {registered ? t("publishedBody") : t("draftBody")}
        </p>
        {problem ? <Alert className="mt-4">{t(problem)}</Alert> : null}
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={() => dialog.current?.close()} autoFocus>
            {t("cancel")}
          </Button>
          <button
            type="button"
            onClick={confirm}
            aria-disabled={busy || undefined}
            className={DANGER_SOLID}
          >
            {busy ? t("deleting") : t("confirm")}
          </button>
        </div>
      </dialog>
    </>
  );
}
