"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button, buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { cn } from "@/components/ui/cn";
import { LinkPending } from "@/components/ui/LinkPending";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/status-icons";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { useHydrated } from "@/lib/hooks/useHydrated";

import type { confirmStepUp } from "../research/calls";
import { LazyStepUp as StepUp } from "../research/LazyStepUp";
import { decideMessageCase } from "./calls";
import { MODERATION_PATH, refusalNext, type Blocked, type Choice, type OutcomeKey, type RefusalCode } from "./moderation";

type MessageChoice = "dismiss" | "uphold";

export interface MessageDecisionProps {
  caseId: string;
  /** The decisions the API accepts from this moderator now (dismiss and uphold for a message report). */
  actions: readonly Choice[];
  blocked: Blocked | null;
  /** A decided report: its outcome and who decided it when (formatted on the server). */
  decided: { outcome: OutcomeKey; line: string } | null;
  nextHref: string | null;
  decideImpl?: typeof decideMessageCase;
  confirmImpl?: typeof confirmStepUp;
}

type Notice = { tone: "ok"; key: "message.dismissed" | "message.upheld" } | { tone: "error"; key: string };

const TONE = {
  ok: { Icon: CheckIcon, className: "text-ok" },
  info: { Icon: InfoIcon, className: "text-accent" },
  error: { Icon: AlertIcon, className: "text-error" },
} as const;

const NOTE_ID = "decision-note";
const BUTTON_ID = { dismiss: "case-dismiss", uphold: "case-uphold" } as const;

/**
 * A moderator's decision on a message report (REQ-ENG-11; POST …/cases/{case_id}/decision with dismiss or uphold and
 * an optional note). Dismiss is the screen's one primary action; each choice asks once more in a dialog. A stale
 * second factor asks for a fresh code inline, then the decision runs again. Every refusal is a fixed sentence; the
 * status line takes focus when it changes. The message itself never changes, whatever is decided.
 */
export function MessageDecision({ caseId, actions, blocked, decided, nextHref, decideImpl = decideMessageCase, confirmImpl }: MessageDecisionProps) {
  const t = useStrings("adminModeration");
  const router = useRouter();
  const hydrated = useHydrated();
  const dialog = useRef<HTMLDialogElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const [note, setNote] = useState("");
  const [asking, setAsking] = useState<MessageChoice>("dismiss");
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState<MessageChoice | null>(null);
  const [done, setDone] = useState(false);
  const [after, setAfter] = useState<"back" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (shown > 0) status.current?.focus();
  }, [shown]);

  function say(next: Notice) {
    setNotice(next);
    setShown((count) => count + 1);
  }

  async function run(choice: MessageChoice) {
    setBusy(true);
    const outcome = await decideImpl(caseId, choice, note);
    setBusy(false);
    dialog.current?.close();
    if (outcome.ok) {
      setStepUp(null);
      setDone(true);
      say({ tone: "ok", key: choice === "dismiss" ? "message.dismissed" : "message.upheld" });
      router.refresh();
      return;
    }
    if (outcome.refusal.kind === "stepUp") {
      setStepUp(choice);
      return;
    }
    setStepUp(null);
    const code: RefusalCode = outcome.refusal.kind === "refusal" ? outcome.refusal.code : "generic";
    say({ tone: "error", key: code === "own_content" ? "message.own" : `refusal.${code}` });
    if (refusalNext(code) === "back") {
      setAfter("back");
      router.refresh();
    }
  }

  const back = (primary: boolean) => (
    <div className="flex flex-col items-start">
      <Link
        href={MODERATION_PATH}
        data-primary={primary ? "" : undefined}
        className={primary ? buttonClass("primary", "no-underline") : standaloneLinkClass}
      >
        {t("decision.back")}
        <LinkPending className="ml-2" />
      </Link>
    </div>
  );

  let body;
  if (done) {
    body = (
      <div className="flex flex-col items-start gap-3">
        {nextHref ? (
          <Link href={nextHref} data-primary="" className={buttonClass("primary", "no-underline")}>
            {t("decision.next")}
          </Link>
        ) : null}
        {back(!nextHref)}
      </div>
    );
  } else if (decided) {
    body = (
      <div className="flex flex-col items-start gap-3">
        <p className="text-ink" data-decided={decided.outcome}>
          {decided.line}
        </p>
        {back(false)}
      </div>
    );
  } else if (after === "back") {
    body = back(true);
  } else if (actions.length === 0) {
    body = (
      <div className="flex flex-col items-start gap-3">
        {blocked ? (
          <NoticeLine tone="info" text={blocked === "own_content" ? t("message.own") : t(`blocked.${blocked}`)} data-blocked={blocked} />
        ) : null}
        {back(false)}
      </div>
    );
  } else if (stepUp) {
    const choice = stepUp;
    body = (
      <StepUp
        confirmImpl={confirmImpl}
        onConfirmed={() => run(choice)}
        onCancel={() => {
          setStepUp(null);
          requestAnimationFrame(() => document.getElementById(BUTTON_ID[choice])?.focus());
        }}
      />
    );
  } else {
    const ask = (choice: MessageChoice) => {
      setAsking(choice);
      openConfirm(dialog.current);
    };
    body = (
      <div className="flex flex-col gap-5">
        <p className="max-w-[60ch] text-ink-soft" data-lead="">
          {t("message.decisionLead")}
        </p>
        <TextAreaField
          id={NOTE_ID}
          label={t("message.noteLabel")}
          hint={t("message.noteHint")}
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          {actions.includes("dismiss") ? (
            <Button id={BUTTON_ID.dismiss} variant="primary" busy={busy} onClick={() => ask("dismiss")}>
              {t("message.dismiss")}
            </Button>
          ) : null}
          {actions.includes("uphold") ? (
            <Button id={BUTTON_ID.uphold} variant="secondary" busy={busy} onClick={() => ask("uphold")}>
              {t("message.uphold")}
            </Button>
          ) : null}
        </div>
        <ConfirmDialog
          ref={dialog}
          title={asking === "dismiss" ? t("message.dismissTitle") : t("message.upholdTitle")}
          confirmLabel={asking === "dismiss" ? t("message.dismissYes") : t("message.upholdYes")}
          busyLabel={asking === "dismiss" ? t("message.dismissing") : t("message.upholding")}
          busy={busy}
          tone={asking === "dismiss" ? "primary" : "danger"}
          onConfirm={() => void run(asking)}
          cancelLabel={t("decision.cancel")}
          bodyProps={{ "data-confirm": asking }}
        >
          <p>{asking === "dismiss" ? t("message.dismissBody") : t("message.upholdBody")}</p>
        </ConfirmDialog>
      </div>
    );
  }

  return (
    <div className="flex flex-col" data-hydrated={hydrated ? "true" : "false"} data-message-decision="">
      {/* The status line stays in the page, empty and without height when there is nothing to say. */}
      <div ref={status} tabIndex={-1} role="status" data-notice={notice?.key} className={cn("focus:outline-none", notice && "mb-4")}>
        {notice ? <NoticeLine tone={notice.tone} text={t(notice.key as "message.dismissed")} /> : null}
      </div>
      {body}
    </div>
  );
}

function NoticeLine({ tone, text, ...rest }: { tone: keyof typeof TONE; text: string; "data-blocked"?: string }) {
  const { Icon, className } = TONE[tone];
  return (
    <p className="flex max-w-[65ch] items-start gap-2 text-ink" {...rest}>
      <Icon className={cn("mt-0.5 size-5 shrink-0", className)} />
      <span>{text}</span>
    </p>
  );
}
