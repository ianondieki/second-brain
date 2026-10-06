"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { RadioGroup } from "@/components/ui/RadioGroup";

import { teamCalls, type TeamCalls } from "../calls";
import { Overflow, overflowItemClass } from "../Overflow";
import type { CreditRefusal } from "../teams";

export interface IdeaChoice {
  id: string;
  title: string;
}

type Dialog = "credit" | "leave" | "block";

/**
 * The thread's own steps (REQ-DEV-03; D-62): "Add as contributor on an idea" (a sheet listing the caller's published
 * ideas; one chosen is credited with the other developer's handle), and, in the overflow menu, "Leave thread" and
 * "Block", each behind a confirmation. What happened is said in a status line that takes focus; leaving and blocking
 * then read the page again, which shows the thread closed.
 */
export function ThreadActions({
  threadId,
  counterpart,
  open,
  ideas,
  calls: given,
}: {
  threadId: string;
  /** The other developer, or null when the caller may no longer see them. */
  counterpart: { user_id: string; handle: string } | null;
  open: boolean;
  /** The caller's published ideas, which the other developer can be credited on. */
  ideas: readonly IdeaChoice[];
  calls?: Partial<TeamCalls>;
}) {
  const t = useStrings("teamUp");
  const router = useRouter();
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(), ...given }));
  const creditDialog = useRef<HTMLDialogElement>(null);
  const leaveDialog = useRef<HTMLDialogElement>(null);
  const blockDialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState<Dialog | null>(null);
  const [problem, setProblem] = useState<{ dialog: Dialog; text: string } | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [said, setSaid] = useState<{ text: string; n: number } | null>(null);
  const [, startRefresh] = useTransition();
  const status = useRef<HTMLDivElement>(null);
  const done = useRef<string | null>(null);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  function dialogOf(dialog: Dialog) {
    return dialog === "credit" ? creditDialog.current : dialog === "leave" ? leaveDialog.current : blockDialog.current;
  }

  function show(dialog: Dialog) {
    setProblem(null);
    if (dialog === "credit") setChosen(null);
    openConfirm(dialogOf(dialog));
  }

  function closed() {
    setProblem(null);
    const text = done.current;
    done.current = null;
    if (text) setSaid((now) => ({ text, n: (now?.n ?? 0) + 1 }));
  }

  async function credit() {
    if (busy || !counterpart) return;
    const idea = ideas.find((item) => item.id === chosen);
    if (!idea) {
      setProblem({ dialog: "credit", text: t("credit.choose") });
      return;
    }
    setBusy("credit");
    const outcome = await calls.credit(idea.id, counterpart.user_id);
    setBusy(null);
    if (!outcome.ok) {
      setProblem({ dialog: "credit", text: t(`credit.${outcome.refusal satisfies CreditRefusal}`) });
      return;
    }
    done.current = t("credit.added", { title: idea.title });
    creditDialog.current?.close();
  }

  async function end(dialog: "leave" | "block") {
    if (busy) return;
    setBusy(dialog);
    const outcome = dialog === "leave" ? await calls.leave(threadId) : counterpart ? await calls.block(counterpart.user_id) : { ok: false };
    setBusy(null);
    if (!outcome.ok) {
      setProblem({ dialog, text: dialog === "leave" ? t("thread.failed") : t("block.failed") });
      return;
    }
    done.current = dialog === "leave" ? t("thread.left") : t("list.blocked", { name: counterpart?.handle ?? "" });
    dialogOf(dialog)?.close();
    startRefresh(() => router.refresh());
  }

  const canCredit = counterpart !== null && ideas.length > 0;
  const menu = open || counterpart !== null;
  if (!canCredit && !menu && !said) return null;
  const alert = (dialog: Dialog) => (problem?.dialog === dialog ? <Alert>{problem.text}</Alert> : null);

  return (
    <div className="flex flex-col gap-4" data-thread-actions="">
      {said ? (
        <Alert key={said.n} ref={status} tone="ok">
          {said.text}
        </Alert>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        {canCredit ? (
          <Button aria-haspopup="dialog" onClick={() => show("credit")} data-add-contributor="">
            {t("credit.add")}
          </Button>
        ) : null}
        {menu ? (
          <Overflow label={t("thread.more")} data-thread-menu="">
            {open ? (
              <button type="button" className={overflowItemClass} aria-haspopup="dialog" onClick={() => show("leave")} data-leave="">
                {t("thread.leave")}
              </button>
            ) : null}
            {counterpart ? (
              <button type="button" className={`${overflowItemClass} text-error`} aria-haspopup="dialog" onClick={() => show("block")} data-block="">
                {t("thread.block", { name: counterpart.handle })}
              </button>
            ) : null}
          </Overflow>
        ) : null}
      </div>

      {canCredit ? (
        <ConfirmDialog
          ref={creditDialog}
          size="lg"
          title={t("credit.title", { name: counterpart.handle })}
          confirmLabel={t("credit.confirm")}
          busyLabel={t("credit.adding")}
          cancelLabel={t("block.cancel")}
          busy={busy === "credit"}
          onConfirm={() => void credit()}
          problem={alert("credit")}
          onClose={closed}
          bodyProps={{ "data-credit-sheet": "", className: "flex flex-col gap-4" }}
        >
          <p className="text-ink-soft">{t("credit.lead")}</p>
          <RadioGroup<string>
            id="credit-idea"
            name="credit-idea"
            legend={t("credit.legend")}
            value={chosen}
            onChange={(id) => {
              setChosen(id);
              setProblem(null);
            }}
            options={ideas.map((idea) => ({ value: idea.id, label: idea.title }))}
          />
        </ConfirmDialog>
      ) : null}

      <ConfirmDialog
        ref={leaveDialog}
        tone="danger"
        title={t("thread.leaveTitle")}
        confirmLabel={t("thread.leaveConfirm")}
        busyLabel={t("thread.leaving")}
        cancelLabel={t("block.cancel")}
        busy={busy === "leave"}
        onConfirm={() => void end("leave")}
        problem={alert("leave")}
        onClose={closed}
      >
        <p>{t("thread.leaveBody")}</p>
      </ConfirmDialog>

      {counterpart ? (
        <ConfirmDialog
          ref={blockDialog}
          tone="danger"
          title={t("block.title", { name: counterpart.handle })}
          confirmLabel={t("block.confirm")}
          busyLabel={t("block.busy")}
          cancelLabel={t("block.cancel")}
          busy={busy === "block"}
          onConfirm={() => void end("block")}
          problem={alert("block")}
          onClose={closed}
        >
          <p>{t("block.body")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
