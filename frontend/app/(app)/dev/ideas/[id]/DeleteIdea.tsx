"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import type { removeIdea } from "../calls";
import { BASE_PATH } from "../paths";

export interface DeleteIdeaProps {
  id: string;
  /** Registered at least once: deleting hides it and keeps the evidence (REQ-PROV-05); a draft is removed. */
  registered: boolean;
  removeImpl?: typeof removeIdea;
}

/**
 * "Delete idea" with a confirmation dialog that says what happens before anything does (docs/spec/06 6.4, AC-IP-6):
 * a published idea is hidden and its registered versions, certificates and /verify records are kept; a draft that was
 * never published is removed. A ConfirmDialog: it traps focus, closes on Escape and returns focus to the button.
 */
// The delete call (and the editor's save helpers it shares a module with) loads on confirmation, not with the page
// (P25: the idea page under the 150 KB budget).
const removeLazily: typeof removeIdea = (id, client) => import("../calls").then((calls) => calls.removeIdea(id, client));

export function DeleteIdea({ id, registered, removeImpl = removeLazily }: DeleteIdeaProps) {
  const t = useStrings("ideaDelete");
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
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
      <Button variant="danger" onClick={() => openConfirm(dialog.current)} aria-haspopup="dialog">
        {t("open")}
      </Button>
      <ConfirmDialog
        ref={dialog}
        tone="danger"
        title={t("title")}
        confirmLabel={t("confirm")}
        busyLabel={t("deleting")}
        cancelLabel={t("cancel")}
        busy={busy}
        onConfirm={() => void confirm()}
        onClose={() => setProblem(null)}
        problem={problem ? <Alert>{t(problem)}</Alert> : null}
      >
        <p>{registered ? t("publishedBody") : t("draftBody")}</p>
      </ConfirmDialog>
    </>
  );
}
