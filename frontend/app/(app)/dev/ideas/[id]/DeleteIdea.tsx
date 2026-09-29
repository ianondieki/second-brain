"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import { removeIdea } from "../calls";
import { BASE_PATH } from "../ideas";

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
  const t = useTranslations("ideaDelete");
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
      <Button
        variant="secondary"
        className="border-error text-error hover:bg-[color-mix(in_oklab,var(--error)_7%,var(--paper))]"
        onClick={() => dialog.current?.showModal()}
        aria-haspopup="dialog"
      >
        {t("open")}
      </Button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onClose={() => setProblem(null)}
        className={cn(
          "m-auto w-[calc(100%-2rem)] max-w-md rounded-panel border border-line bg-paper p-6 text-ink",
          "backdrop:bg-[color-mix(in_oklab,var(--ink)_45%,transparent)]",
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
            className={buttonClass(
              "secondary",
              "border-error bg-error text-on-accent hover:bg-[color-mix(in_oklab,var(--error)_84%,var(--ink))] hover:text-on-accent",
            )}
          >
            {busy ? t("deleting") : t("confirm")}
          </button>
        </div>
      </dialog>
    </>
  );
}
