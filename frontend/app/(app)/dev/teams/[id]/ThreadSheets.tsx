"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { RadioGroup } from "@/components/ui/RadioGroup";

import { teamCalls, type TeamCalls } from "../calls";
import type { CreditRefusal } from "../teams";

// Loaded with the first press of one of the thread's steps (TeamThread.tsx, through ./later): the route carries none of
// the dialogs, the radio list or their calls until then (docs/spec/07 item 5, 150 KB per route).

export type Sheet = "credit" | "leave" | "block";

export interface IdeaChoice {
  id: string;
  title: string;
}

/**
 * One of the thread's step dialogs, opened as a modal on mount: "Add as contributor" (the caller's published ideas,
 * one chosen), "Leave thread" or "Block", each saying what happens first. Once a step is done the dialog closes and
 * a status line here says what happened (it takes focus and stays until the next step is pressed); leaving and
 * blocking then read the page again, which shows the thread closed.
 */
export function ThreadSheets({
  sheet,
  threadId,
  counterpart,
  ideas,
  calls: given,
}: {
  sheet: Sheet;
  threadId: string;
  counterpart: { user_id: string; handle: string } | null;
  ideas: readonly IdeaChoice[];
  /** Tests pass fakes; the real calls otherwise. */
  calls?: Partial<TeamCalls>;
}) {
  const t = useStrings("teamUp");
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(), ...given }));
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const done = useRef<string | null>(null);
  const router = useRouter();
  const [, startRefresh] = useTransition();
  const [said, setSaid] = useState<string | null>(null);
  const status = useRef<HTMLDivElement>(null);

  useEffect(() => {
    openConfirm(dialog.current);
  }, []);
  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  async function confirm() {
    if (busy) return;
    if (sheet === "credit") {
      const idea = ideas.find((item) => item.id === chosen);
      if (!idea || !counterpart) {
        setProblem(t("credit.choose"));
        return;
      }
      setBusy(true);
      const outcome = await calls.credit(idea.id, counterpart.user_id);
      setBusy(false);
      if (!outcome.ok) {
        setProblem(t(`credit.${outcome.refusal satisfies CreditRefusal}`));
        return;
      }
      done.current = t("credit.added", { title: idea.title });
    } else {
      setBusy(true);
      const outcome =
        sheet === "leave"
          ? await calls.leave(threadId)
          : counterpart
            ? await calls.block(counterpart.user_id)
            : { ok: false };
      setBusy(false);
      if (!outcome.ok) {
        setProblem(sheet === "leave" ? t("thread.failed") : t("block.failed"));
        return;
      }
      done.current = sheet === "leave" ? t("thread.left") : t("list.blocked", { name: counterpart?.handle ?? "" });
    }
    dialog.current?.close();
  }

  const name = counterpart?.handle ?? "";
  const frame =
    sheet === "credit"
      ? {
          title: t("credit.title", { name }),
          confirmLabel: t("credit.confirm"),
          busyLabel: t("credit.adding"),
          tone: "primary" as const,
        }
      : sheet === "leave"
        ? {
            title: t("thread.leaveTitle"),
            confirmLabel: t("thread.leaveConfirm"),
            busyLabel: t("thread.leaving"),
            tone: "danger" as const,
          }
        : {
            title: t("block.title", { name }),
            confirmLabel: t("block.confirm"),
            busyLabel: t("block.busy"),
            tone: "danger" as const,
          };

  return (
    <>
      {said ? (
        <Alert ref={status} tone="ok">
          {said}
        </Alert>
      ) : null}
      <ConfirmDialog
        ref={dialog}
        {...frame}
        size={sheet === "credit" ? "lg" : "md"}
        cancelLabel={t("block.cancel")}
        busy={busy}
        onConfirm={() => void confirm()}
        problem={problem ? <Alert>{problem}</Alert> : null}
        onClose={() => {
          const text = done.current;
          if (!text) return;
          setSaid(text);
          if (sheet !== "credit") startRefresh(() => router.refresh());
        }}
        bodyProps={{ [`data-${sheet}-sheet`]: "", className: "flex flex-col gap-4" }}
      >
        {sheet === "credit" ? (
          <>
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
          </>
        ) : (
          <p>{sheet === "leave" ? t("thread.leaveBody") : t("block.body")}</p>
        )}
      </ConfirmDialog>
    </>
  );
}
