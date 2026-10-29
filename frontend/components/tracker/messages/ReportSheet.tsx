"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import type { ThreadCalls } from "./calls";
import { REPORT_REASONS, type Message, type ReportReason, type ReportRefusal } from "./thread";

// Loaded on the first press of a Report (Thread.tsx): the Messages route carries none of it until then (docs/spec/07
// item 5, 150 KB per route).

/**
 * The report sheet (one for the thread): the five reasons as checkboxes, at least one, and a confirm. The report shares
 * that one message with the moderators; it stays in the thread for both sides. It opens as a modal for each new
 * `target` (focus goes back to that message's Report when it closes).
 */
export function ReportSheet({
  engagementId,
  target,
  onReported,
  calls,
}: {
  engagementId: string;
  /** The message to report, a new object each press. */
  target: { message: Message };
  onReported: (message: Message, created: boolean) => void;
  calls: ThreadCalls;
}) {
  const t = useStrings("trackerMessages");
  const dialog = useRef<HTMLDialogElement>(null);
  const [reasons, setReasons] = useState<ReportReason[]>([]);
  const [problem, setProblem] = useState<ReportRefusal | "reportNeedsReason" | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    openConfirm(dialog.current);
  }, [target]);

  async function send() {
    if (reasons.length === 0) {
      setProblem("reportNeedsReason");
      return;
    }
    setBusy(true);
    setProblem(null);
    const outcome = await calls.reportMessage(engagementId, target.message.id, reasons);
    setBusy(false);
    if (!outcome.ok) {
      setProblem(outcome.refusal);
      return;
    }
    dialog.current?.close();
    onReported(target.message, outcome.created);
  }

  return (
    <ConfirmDialog
      ref={dialog}
      title={t("reportTitle")}
      confirmLabel={t("reportConfirm")}
      busyLabel={t("reportBusy")}
      busy={busy}
      onConfirm={() => void send()}
      cancelLabel={t("cancel")}
      problem={problem ? <Alert>{t(problem)}</Alert> : null}
      onClose={() => {
        setReasons([]);
        setProblem(null);
      }}
    >
      <p className="text-ink-soft">{t("reportLead")}</p>
      <fieldset className="mt-4" data-report-reasons="">
        <legend className="font-semibold text-ink">{t("reasonsLegend")}</legend>
        {REPORT_REASONS.map((reason) => (
          <Checkbox
            key={reason}
            id={`report-reason-${reason}`}
            label={t(`reason.${reason}`)}
            checked={reasons.includes(reason)}
            onChange={(event) => {
              const on = event.currentTarget.checked;
              setReasons((now) => (on ? [...now, reason] : now.filter((r) => r !== reason)));
              setProblem(null);
            }}
          />
        ))}
      </fieldset>
    </ConfirmDialog>
  );
}
