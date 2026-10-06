"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { teamCalls, type TeamCalls } from "./calls";
import type { Contribution } from "./teams";

/**
 * The ideas that credit the caller as a contributor (REQ-DEV-03; D-62 (a)), on /dev/teams: "You are a contributor on
 * {title}" each, with "Leave" behind a confirmation (the credit comes off the idea and its certificate for good). A
 * status line says it is done and takes focus.
 */
export function Credits({ initial, calls: given }: { initial: readonly Contribution[]; calls?: Partial<TeamCalls> }) {
  const t = useStrings("teamUp");
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(), ...given }));
  const dialog = useRef<HTMLDialogElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const [items, setItems] = useState(initial);
  const [target, setTarget] = useState<Contribution | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const [said, setSaid] = useState<{ text: string; n: number } | null>(null);
  const left = useRef(false);

  useEffect(() => {
    if (target) openConfirm(dialog.current);
  }, [target]);
  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  const title = (item: Contribution) => item.title ?? t("credit.unpublished");

  async function leave() {
    if (!target || state === "busy") return;
    setState("busy");
    const outcome = await calls.leaveCredit(target.proposal_id);
    if (!outcome.ok) {
      setState("failed");
      return;
    }
    left.current = true;
    dialog.current?.close();
  }

  return (
    <div className="flex flex-col gap-4">
      {said ? (
        <Alert key={said.n} ref={status} tone="ok">
          {said.text}
        </Alert>
      ) : null}
      {items.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line border-y border-line" data-credits="">
          {items.map((item) => (
            <li key={item.proposal_id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3" data-credit={item.proposal_id}>
              <span id={`credit-${item.proposal_id}`} className="min-w-0 text-ink [overflow-wrap:anywhere]">
                {t("credit.youAre", { title: title(item) })}
              </span>
              <Button
                variant="link"
                aria-haspopup="dialog"
                aria-describedby={`credit-${item.proposal_id}`}
                onClick={() => {
                  setState("idle");
                  setTarget(item);
                }}
                data-leave-credit=""
              >
                {t("credit.leave")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <ConfirmDialog
        ref={dialog}
        tone="danger"
        title={target ? t("credit.leaveTitle", { title: title(target) }) : ""}
        confirmLabel={t("credit.leaveConfirm")}
        busyLabel={t("credit.leaving")}
        cancelLabel={t("block.cancel")}
        busy={state === "busy"}
        onConfirm={() => void leave()}
        problem={state === "failed" ? <Alert>{t("credit.leaveFailed")}</Alert> : null}
        onClose={() => {
          const gone = target;
          setTarget(null);
          setState("idle");
          if (gone && left.current) {
            left.current = false;
            setItems((now) => now.filter((item) => item.proposal_id !== gone.proposal_id));
            setSaid((now) => ({ text: t("credit.left", { title: title(gone) }), n: (now?.n ?? 0) + 1 }));
          }
        }}
      >
        <p>{t("credit.leaveBody")}</p>
      </ConfirmDialog>
    </div>
  );
}
